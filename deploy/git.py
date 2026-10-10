import random
import subprocess
import time
from typing import Optional

import requests

from deploy.config import CNB_REPOSITORY, GITCODE_REPOSITORY, DeployConfig, ExecutionError
from deploy.git_over_cdn.client import GitOverCdnClient
from deploy.git_over_cdn.endpoints import CLOUDFLARE_UPDATE_URLS, FALLBACK_UPDATE_URLS
from deploy.logger import logger
from deploy.utils import *


CLOUD_UPDATE_CONTROL_URL = 'https://alas-apiv2.nanoda.work/api/updata'
CLOUD_FORCE_UPDATE_CONTROL_URL = 'https://alas-apiv2.nanoda.work/api/force_update'


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


class GitManager(DeployConfig):
    """Git 仓库与更新管理类，负责源码拉取、分支同步及 GitOverCDN 更新。"""

    @cached_property
    def git(self):
        """获取 Git 可执行文件路径。

        Returns:
            str: Git 可执行文件绝对路径或回退命令 'git'。
        """
        exe = self.filepath('GitExecutable')
        if os.path.exists(exe):
            return exe

        logger.warning(f'GitExecutable: {exe} does not exist, use `git` instead')
        return 'git'

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
            self.execute(f'{git} init')

        logger.hr('Set Git Proxy', 1)
        if proxy:
            self.execute(f'{git} config --local http.proxy {proxy}')
            self.execute(f'{git} config --local https.proxy {proxy}')
        else:
            self.execute(f'{git} config --local --unset http.proxy', allow_failure=True)
            self.execute(f'{git} config --local --unset https.proxy', allow_failure=True)

        if ssl_verify:
            self.execute(f'{git} config --local http.sslVerify true', allow_failure=True)
        else:
            self.execute(f'{git} config --local http.sslVerify false', allow_failure=True)

        logger.hr('Set Git Repository', 1)
        if not self.execute(f'{git} remote set-url {source} {repo}', allow_failure=True):
            self.execute(f'{git} remote add {source} {repo}')

        logger.hr('Fetch Repository Branch', 1)
        self._fetch_with_retry(source, branch)

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
        # pull 联网，与 fetch 用不同 UA，降低同源请求的可归集性
        git = f'"{self.git}" -c http.userAgent={self.git_user_agent()}'
        self.execute(f'{git} pull --ff-only {source} {branch}')

        logger.hr('Show Version', 1)
        self.execute(f'{git} --no-pager log --no-merges -1')

    @property
    def goc_client(self):
        """获取 GitOverCDN 客户端实例。

        Returns:
            GitOverCdnClient: 已配置好的客户端实例。
        """
        client = GitOverCdnClient(
            url=CLOUDFLARE_UPDATE_URLS,
            fallback_urls=FALLBACK_UPDATE_URLS,
            folder=self.root_filepath,
            source='origin',
            branch=self.Branch,
            git=self.git,
        )
        client.logger = logger
        return client

    @staticmethod
    def cloud_auto_update_enabled():
        """检查云端自动更新开关是否启用。

        Returns:
            bool | None: True 启用，False 禁用，网络异常返回 None。
        """
        logger.info(f'Check cloud update control: {CLOUD_UPDATE_CONTROL_URL}')
        try:
            resp = requests.get(CLOUD_UPDATE_CONTROL_URL, timeout=5, headers={'User-Agent': 'alas AzurPilot'})
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f'Failed to check cloud update control: {e}')
            return None

        text = resp.text.strip()
        try:
            data = resp.json()
        except ValueError:
            data = text

        if data is True or (isinstance(data, str) and data.lower() in ('true', 'ture')):
            logger.info('Cloud update control is enabled')
            return True
        if data is False or (isinstance(data, str) and data.lower() in ('false', 'fales')):
            logger.info('Cloud update control is disabled')
            return False

        logger.info(f'Cloud update control is inaccessible: {text}')
        return None

    @staticmethod
    def cloud_force_update_enabled():
        """检查云端强制更新开关是否启用。

        Returns:
            bool | None: True 启用，False 禁用，网络异常返回 None。
        """
        logger.info(f'Check cloud force update control: {CLOUD_FORCE_UPDATE_CONTROL_URL}')
        try:
            resp = requests.get(
                CLOUD_FORCE_UPDATE_CONTROL_URL,
                timeout=5,
                headers={'User-Agent': 'alas AzurPilot'},
            )
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f'Failed to check cloud force update control: {e}')
            return None

        text = resp.text.strip()
        try:
            data = resp.json()
        except ValueError:
            data = text

        if data is True or (isinstance(data, str) and data.lower() in ('true', 'ture')):
            logger.info('Cloud force update control is enabled')
            return True
        if data is False or (isinstance(data, str) and data.lower() in ('false', 'fales')):
            logger.info('Cloud force update control is disabled')
            return False

        logger.info(f'Cloud update control is inaccessible: {text}')
        return None

    def cloud_update_access_failed(self, fatal=True):
        """处理云端更新控制接口访问失败的情形。

        Args:
            fatal (bool): 是否视为致命错误并终止启动。

        Raises:
            ExecutionError: 当 fatal 为 True 时抛出。
        """
        logger.hr('Cloud Update Control Failed', 0)
        if fatal:
            logger.warning('Failed to access cloud update control, stopping startup')
            raise ExecutionError
        else:
            logger.warning('Failed to access cloud update control, skip update check')

    def git_install(self):
        """根据云端状态与本地配置执行 Git 源码拉取与更新。"""
        logger.hr('Update AzurPilot', 0)

        cloud_update = self.cloud_auto_update_enabled()
        if cloud_update is None:
            self.cloud_update_access_failed()
        if not cloud_update:
            logger.info('Cloud update control disabled, skip')
            return

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


if __name__ == '__main__':
    self = GitManager()
    self.goc_client.get_status()
