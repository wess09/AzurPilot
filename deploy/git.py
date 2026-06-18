import requests

from deploy.config import DeployConfig, ExecutionError
from deploy.git_over_cdn.client import GitOverCdnClient
from deploy.logger import logger
from deploy.utils import *


CLOUD_UPDATE_CONTROL_URL = 'https://alas-apiv2.nanoda.work/api/updata'


class GitManager(DeployConfig):
    @cached_property
    def git(self):
        exe = self.filepath('GitExecutable')
        if os.path.exists(exe):
            return exe

        logger.warning(f'GitExecutable: {exe} does not exist, use `git` instead')
        return 'git'

    @staticmethod
    def remove(file):
        try:
            os.remove(file)
            logger.info(f'Removed file: {file}')
        except FileNotFoundError:
            logger.info(f'File not found: {file}')

    def git_repository_init(
            self, repo, source='origin', branch='master', proxy='', ssl_verify=True
    ):
        logger.hr('Git Init', 1)
        if not self.execute(f'"{self.git}" init', allow_failure=True):
            self.remove('./.git/config')
            self.remove('./.git/index')
            self.remove('./.git/HEAD')
            self.execute(f'"{self.git}" init')

        logger.hr('Set Git Proxy', 1)
        if proxy:
            self.execute(f'"{self.git}" config --local http.proxy {proxy}')
            self.execute(f'"{self.git}" config --local https.proxy {proxy}')
        else:
            self.execute(f'"{self.git}" config --local --unset http.proxy', allow_failure=True)
            self.execute(f'"{self.git}" config --local --unset https.proxy', allow_failure=True)

        if ssl_verify:
            self.execute(f'"{self.git}" config --local http.sslVerify true', allow_failure=True)
        else:
            self.execute(f'"{self.git}" config --local http.sslVerify false', allow_failure=True)

        logger.hr('Set Git Repository', 1)
        if not self.execute(f'"{self.git}" remote set-url {source} {repo}', allow_failure=True):
            self.execute(f'"{self.git}" remote add {source} {repo}')

        logger.hr('Fetch Repository Branch', 1)
        self.execute(f'"{self.git}" fetch {source} {branch}')

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
        self.execute(f'"{self.git}" reset --hard {source}/{branch}')
        self.execute(f'"{self.git}" pull --ff-only {source} {branch}')

        logger.hr('Show Version', 1)
        self.execute(f'"{self.git}" --no-pager log --no-merges -1')

    @property
    def goc_client(self):
        client = GitOverCdnClient(
            url=[
                'https://alas.nanoda.work/upd',
                'https://1825239988.v.123pan.cn/1825239988/azur/AzurPilot_master',
            ],
            folder=self.root_filepath,
            source='origin',
            branch='master',
            git=self.git,
        )
        client.logger = logger
        return client

    @staticmethod
    def cloud_auto_update_enabled():
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

    def cloud_update_access_failed(self, fatal=True):
        logger.hr('Cloud Update Control Failed', 0)
        if fatal:
            logger.warning('Failed to access cloud update control, stopping startup')
            raise ExecutionError
        else:
            logger.warning('Failed to access cloud update control, skip update check')

    def git_install(self):
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
