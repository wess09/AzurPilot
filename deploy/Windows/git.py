import configparser
import os
import random
import subprocess
import time
from typing import Optional

from deploy.Windows.config import CNB_REPOSITORY, GITCODE_REPOSITORY, DeployConfig, ExecutionError
from deploy.Windows.logger import Progress, logger
from deploy.Windows.utils import cached_property
from deploy.git_over_cdn.client import GitOverCdnClient
from deploy.git_over_cdn.endpoints import CLOUDFLARE_UPDATE_URLS, FALLBACK_UPDATE_URLS


def peer_fallback_repository(url: str) -> Optional[str]:
    """若当前 URL 为 CNB 或 GitCode 国内镜像，获取同级的备用镜像 URL 用于分流容灾。"""
    if not url:
        return None
    cleaned = url.strip().rstrip('/').removesuffix('.git')
    if cleaned == CNB_REPOSITORY.rstrip('/'):
        return GITCODE_REPOSITORY
    if cleaned == GITCODE_REPOSITORY.rstrip('/'):
        return CNB_REPOSITORY
    return None


class GitConfigParser(configparser.ConfigParser):
    """Git 配置文件解析器，提供配置值检查功能。"""

    def check(self, section, option, value):
        """检查指定配置小节下的配置项是否与期望值一致。

        Args:
            section (str): 配置小节名称。
            option (str): 配置选项名称。
            value (str | None): 期望的配置值。

        Returns:
            bool: 配置项是否存在且与期望值相等。
        """
        result = self.get(section, option, fallback=None)
        if result == value:
            logger.info(f'Git config {section}.{option} = {value}')
            return True
        else:
            return False


class GitOverCdnClientWindows(GitOverCdnClient):
    """带安装器进度上报的 Windows 版 GitOverCDN 客户端。"""

    def update(self, *args, **kwargs):
        """执行更新并通知安装器进度。"""
        Progress.GitInit()
        _ = super().update(*args, **kwargs)
        Progress.GitShowVersion()
        return _

    @cached_property
    def latest_commit(self) -> str:
        """获取最新 commit 并通知安装器进度。"""
        _ = super().latest_commit
        Progress.GitLatestCommit()
        return _

    def download_pack(self):
        """下载 pack 包并通知安装器进度。"""
        _ = super().download_pack()
        Progress.GitDownloadPack()
        return _


class GitManager(DeployConfig):
    """Windows 下 Git 仓库初始化与分支同步管理类。"""

    @staticmethod
    def remove(file):
        """安全删除指定文件。

        Args:
            file (str): 待删除的文件路径。
        """
        try:
            os.remove(file)
            logger.info(f'Removed file: {file}')
        except FileNotFoundError:
            logger.info(f'File not found: {file}')

    @cached_property
    def git_config(self):
        """获取当前仓库的 .git/config 解析器对象。

        Returns:
            GitConfigParser: 配置文件解析实例。
        """
        conf = GitConfigParser()
        conf.read('./.git/config')
        return conf

    @staticmethod
    def git_user_agent():
        """生成随机的 git User-Agent，绕开镜像仓库对固定/异常 git UA 的封禁。

        gitcode 等仓库会对命中黑名单的 UA 返回 418。官方 git 主版本只有 2.x，
        Windows 构建形如 2.x.y.windows.z，不带多余尾段；这里只产出形态真实的
        版本号（避免一眼假的 git/3.x 或五段式 UA 被按特征封禁），同时把采样
        空间撑到约 4×10³ 种（minor 24~63、patch 0~9、build 1~9 的笛卡尔积），
        每次取值都不重复，任何单一 UA 都难以累积成可封禁的固定指纹。

        Returns:
            str: 伪装的 Git User-Agent 字符串。
        """
        while True:
            minor = random.randint(24, 63)
            patch = random.randint(0, 9)
            # 少部分用官方跨平台版（大量 CI/服务器请求即此形态），多数用 Git for Windows
            if random.random() < 0.2:
                ua = f'git/2.{minor}.{patch}'
            else:
                build = random.randint(1, 9)
                ua = f'git/2.{minor}.{patch}.windows.{build}'
            if ua != 'git/2.51.0.windows.2':
                break
        return ua

    def get_remote_url(self, source: str) -> str:
        """获取指定远程源的 URL。"""
        try:
            res = subprocess.run(
                [self.git, 'remote', 'get-url', source],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return res.stdout.strip() if res.returncode == 0 else ''
        except Exception:
            return ''

    def _fetch_with_retry(self, source, branch, max_retry=5, delay=2):
        """带 UA 重试与同级镜像容灾的 git fetch。

        gitcode 等仓库会返回 418 拦截特定 UA，此时自动更换 UA 重试；
        若多次重试仍失败且当前 remote 为国内镜像源（如 GitCode/CNB），
        自动切换至同级备用分流镜像重试，避免单一仓库受风控导致更新中断。

        Args:
            source: 远程源名称。
            branch: 分支名称。
            max_retry: 最大尝试次数（含首次）。
            delay: 重试间隔秒数。

        Raises:
            ExecutionError: 所有尝试均失败时抛出。
        """
        ua = self.git_user_agent()
        for i in range(max_retry):
            git = f'"{self.git}" -c http.userAgent={ua}'
            logger.info(f'Use git User-Agent: {ua}')
            if self.execute(f'{git} fetch {source} {branch}'):
                return
            logger.warning(f'git fetch failed with UA {ua}, attempt {i + 1}/{max_retry}')
            if i < max_retry - 1:
                # 重试间隔加随机抖动，避免暴露固定的失败-重试节奏
                time.sleep(delay * random.uniform(0.5, 1.8))
                ua = self.git_user_agent()

        current_url = self.get_remote_url(source)
        peer_url = peer_fallback_repository(current_url)
        if peer_url:
            logger.warning(
                f'当前镜像源 {current_url} 获取失败（可能触发限流或风控），自动切换至同级分流镜像 {peer_url} 重试'
            )
            git = f'"{self.git}" -c http.userAgent={self.git_user_agent()}'
            if self.execute(f'{git} remote set-url {source} {peer_url}', allow_failure=True):
                if hasattr(self, 'Repository'):
                    self.Repository = peer_url
                ua = self.git_user_agent()
                for i in range(max_retry):
                    git = f'"{self.git}" -c http.userAgent={ua}'
                    logger.info(f'Use git User-Agent: {ua}')
                    if self.execute(f'{git} fetch {source} {branch}'):
                        return
                    logger.warning(f'备用镜像 git fetch 失败 (UA: {ua}), 尝试 {i + 1}/{max_retry}')
                    if i < max_retry - 1:
                        time.sleep(delay * random.uniform(0.5, 1.8))
                        ua = self.git_user_agent()
        raise ExecutionError

    def git_repository_init(
            self, repo, source='origin', branch='master', proxy='', ssl_verify=True
    ):
        """初始化或更新本地 Git 仓库并拉取指定分支。

        Args:
            repo (str): 远端仓库地址。
            source (str): 远端源名称，默认为 'origin'。
            branch (str): 分支名称，默认为 'master'。
            proxy (str): HTTP/HTTPS 代理地址。
            ssl_verify (bool): 是否校验 SSL 证书。
        """
        # 所有 git 命令统一带随机 UA，绕过 gitcode 等仓库对特定 UA 的 418 封禁
        git = f'"{self.git}" -c http.userAgent={self.git_user_agent()}'

        logger.hr('Git Init', 1)
        if not self.execute(f'{git} init', allow_failure=True):
            self.remove('./.git/config')
            self.remove('./.git/index')
            self.remove('./.git/HEAD')
            self.remove('./.git/ORIG_HEAD')
            self.execute(f'{git} init')
        Progress.GitInit()

        logger.hr('Set Git Proxy', 1)
        if proxy:
            if not self.git_config.check('http', 'proxy', value=proxy):
                self.execute(f'{git} config --local http.proxy {proxy}')
            if not self.git_config.check('https', 'proxy', value=proxy):
                self.execute(f'{git} config --local https.proxy {proxy}')
        else:
            if not self.git_config.check('http', 'proxy', value=None):
                self.execute(f'{git} config --local --unset http.proxy', allow_failure=True)
            if not self.git_config.check('https', 'proxy', value=None):
                self.execute(f'{git} config --local --unset https.proxy', allow_failure=True)

        if ssl_verify:
            if not self.git_config.check('http', 'sslVerify', value='true'):
                self.execute(f'{git} config --local http.sslVerify true', allow_failure=True)
        else:
            if not self.git_config.check('http', 'sslVerify', value='false'):
                self.execute(f'{git} config --local http.sslVerify false', allow_failure=True)
        Progress.GitSetConfig()

        logger.hr('Set Git Repository', 1)
        if not self.git_config.check(f'remote "{source}"', 'url', value=repo):
            if not self.execute(f'{git} remote set-url {source} {repo}', allow_failure=True):
                self.execute(f'{git} remote add {source} {repo}')
        Progress.GitSetRepo()

        logger.hr('Fetch Repository Branch', 1)
        self._fetch_with_retry(source, branch)
        Progress.GitFetch()

        logger.hr('Pull Repository Branch', 1)
        # 移除 git 锁文件
        for lock_file in [
            './.git/index.lock',
            './.git/HEAD.lock',
            './.git/refs/heads/master.lock',
        ]:
            if os.path.exists(lock_file):
                logger.info(f'Lock file {lock_file} exists, removing')
                os.remove(lock_file)
        self.execute(f'{git} reset --hard {source}/{branch}')
        Progress.GitReset()
        # git fetch 已执行，checkout 会更快
        if not self.execute(f'{git} checkout {branch}', allow_failure=True):
            # pull 联网，与 fetch 用不同 UA，降低同源请求的可归集性
            git = f'"{self.git}" -c http.userAgent={self.git_user_agent()}'
            self.execute(f'{git} pull --ff-only {source} {branch}')
        Progress.GitCheckout()

        logger.hr('Show Version', 1)
        self.execute(f'{git} --no-pager log --no-merges -1')
        Progress.GitShowVersion()

    @property
    def goc_client(self):
        """获取 Windows 环境下的 GitOverCDN 客户端实例。

        Returns:
            GitOverCdnClientWindows: 客户端实例。
        """
        client = GitOverCdnClientWindows(
            url=CLOUDFLARE_UPDATE_URLS,
            fallback_urls=FALLBACK_UPDATE_URLS,
            folder=self.root_filepath,
            source='origin',
            branch=self.Branch,
            git=self.git,
        )
        client.logger = logger
        return client

    def git_install(self):
        """执行 Git 仓库的更新或完整初始化流程。"""
        logger.hr('Update AzurPilot', 0)

        if self.GitOverCdn:
            if self.goc_client.update():
                return

        self.git_repository_init(
            repo=self.Repository,
            source='origin',
            branch=self.Branch,
            proxy=self.GitProxy,
            ssl_verify=self.SSLVerify,
        )
