import configparser
import os
import random
import time

from deploy.Windows.config import DeployConfig, ExecutionError
from deploy.Windows.logger import Progress, logger
from deploy.Windows.utils import cached_property
from deploy.git_over_cdn.client import GitOverCdnClient
from deploy.git_over_cdn.endpoints import CLOUDFLARE_UPDATE_URLS, FALLBACK_UPDATE_URLS
from deploy.update_cleanup import ObsoleteFileCleaner


class GitConfigParser(configparser.ConfigParser):
    def check(self, section, option, value):
        result = self.get(section, option, fallback=None)
        if result == value:
            logger.info(f'Git config {section}.{option} = {value}')
            return True
        else:
            return False


class GitOverCdnClientWindows(GitOverCdnClient):
    def update(self, *args, **kwargs):
        Progress.GitInit()
        _ = super().update(*args, **kwargs)
        Progress.GitShowVersion()
        return _

    @cached_property
    def latest_commit(self) -> str:
        _ = super().latest_commit
        Progress.GitLatestCommit()
        return _

    def download_pack(self):
        _ = super().download_pack()
        Progress.GitDownloadPack()
        return _


class GitManager(DeployConfig):
    @staticmethod
    def remove(file):
        try:
            os.remove(file)
            logger.info(f'Removed file: {file}')
        except FileNotFoundError:
            logger.info(f'File not found: {file}')

    @cached_property
    def git_config(self):
        conf = GitConfigParser()
        conf.read('./.git/config')
        return conf

    @staticmethod
    def git_user_agent():
        """生成随机的 git User-Agent，绕开部分镜像仓库对特定 git 版本的封禁。

        版本号各段与构建后缀均由随机数生成器产出，每次更新 UA 都不同，
        避免命中 gitcode 等仓库针对特定 UA 字符串的封禁（418）。
        """
        while True:
            major = random.randint(2, 3)
            minor = random.randint(30, 59)
            patch = random.randint(0, 9)
            build = random.randint(1, 5)
            sub = random.randint(1, 9999)
            if random.random() < 0.3:
                ua = f'git/{major}.{minor}.{patch}'
            elif random.random() < 0.6:
                ua = f'git/{major}.{minor}.{patch}.windows.{build}'
            else:
                ua = f'git/{major}.{minor}.{patch}.windows.{build}.{sub}'
            if not ua.startswith('git/2.51.0.windows.2'):
                break
        return ua

    def _fetch_with_retry(self, source, branch, max_retry=5, delay=2):
        """带 UA 重试的 git fetch。

        gitcode 等仓库会返回 418 拦截特定 UA，此时自动更换 UA 重试。

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
                time.sleep(delay)
                ua = self.git_user_agent()
        raise ExecutionError

    def git_repository_init(
            self, repo, source='origin', branch='master', proxy='', ssl_verify=True
    ):
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

        obsolete_file_cleaner = ObsoleteFileCleaner(self.root_filepath, self.git, logger)
        obsolete_file_cleaner.prepare()

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
            self.execute(f'{git} pull --ff-only {source} {branch}')
        Progress.GitCheckout()
        obsolete_file_cleaner.finish()

        logger.hr('Show Version', 1)
        self.execute(f'{git} --no-pager log --no-merges -1')
        Progress.GitShowVersion()

    @property
    def goc_client(self):
        client = GitOverCdnClient(
            url=CLOUDFLARE_UPDATE_URLS,
            fallback_urls=FALLBACK_UPDATE_URLS,
            folder=self.root_filepath,
            source='origin',
            branch='master',
            git=self.git,
        )
        client.logger = logger
        return client

    def git_install(self):
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
