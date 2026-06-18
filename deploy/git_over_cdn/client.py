import io
import json
import os
import re
import shutil
import subprocess
import zipfile
from typing import Callable, Generic, TypeVar

import requests
from requests.adapters import HTTPAdapter

T = TypeVar("T")

TEMPLATE_FILE = './config/template.yaml'


class cached_property(Generic[T]):
    """带类型支持的缓存属性描述符。

    属性只在首次访问时计算一次，之后替换为普通属性。
    删除属性后会重新计算。
    """

    def __init__(self, func: Callable[..., T]):
        self.func = func

    def __get__(self, obj, cls) -> T:
        if obj is None:
            return self

        value = obj.__dict__[self.func.__name__] = self.func(obj)
        return value


class PrintLogger:
    info = print
    warning = print
    error = print

    @staticmethod
    def attr(name, text):
        print(f'[{name}] {text}')


class GitOverCdnClient:
    logger = PrintLogger()

    def __init__(self, url, folder, source='origin', branch='master', git='git'):
        """初始化 Git over CDN 客户端。

        Args:
            url (str | list[str]): CDN 服务地址，如 'http://127.0.0.1:22251/pack/...'。
            folder: 本地仓库路径，如 'D:/AzurLaneAutoScript'。
            source: 远程源名称，默认 'origin'。
            branch: 分支名称，默认 'master'。
            git: git 可执行文件路径。
        """
        if isinstance(url, str):
            self.urls = [url.strip('/')]
        else:
            self.urls = [u.strip('/') for u in url]
        self.url = self.urls[0]
        self.folder = folder.replace('\\', '/')
        self.source = source
        self.branch = branch
        self.git = git

    def filepath(self, path):
        path = os.path.join(self.folder, '.git', path)
        return os.path.abspath(path).replace('\\', '/')

    def urlpath(self, path):
        return f'{self.url}{path}'

    @cached_property
    def current_commit(self) -> str:
        for file in [
            f'./refs/remotes/{self.source}/{self.branch}',
            f'./refs/heads/{self.branch}',
            'ORIG_HEAD',
        ]:
            file = self.filepath(file)
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    commit = f.read()
                res = re.search(r'([0-9a-f]{40})', commit)
                if res:
                    commit = res.group(1)
                    self.logger.attr('CurrentCommit', commit)
                    return commit
            except FileNotFoundError as e:
                self.logger.error(f'Failed to get local commit: {e}')
            except Exception as e:
                self.logger.error(f'Failed to get local commit: {e}')
        return ''

    @property
    def session(self):
        session = requests.Session()
        session.trust_env = False
        session.mount('http://', HTTPAdapter(max_retries=3))
        session.mount('https://', HTTPAdapter(max_retries=3))
        return session

    @cached_property
    def latest_commit(self) -> str:
        for url_base in self.urls:
            self.url = url_base
            url = self.urlpath('/latest.json')
            self.logger.info(f'Fetch url: {url}')
            try:
                resp = self.session.get(url, timeout=3)
            except Exception as e:
                self.logger.error(f'Failed to get remote commit: {e}')
                continue

            if resp.status_code == 200:
                try:
                    info = json.loads(resp.text)
                    commit = info['commit']
                    self.logger.attr('LatestCommit', commit)
                    return commit
                except json.JSONDecodeError:
                    self.logger.error(f'Failed to get remote commit, response is not a json: {resp.text}')
                except KeyError:
                    self.logger.error(f'Failed to get remote commit, key "commit" is not found: {resp.text}')
            else:
                self.logger.error(f'Failed to get remote commit, status={resp.status_code}, text={resp.text}')

        self.url = self.urls[0]
        return ''

    def download_pack(self):
        try:
            url = self.urlpath(f'/{self.latest_commit}/{self.current_commit}.zip')
            self.logger.info(f'Fetch url: {url}')
            resp = self.session.get(url, timeout=20)
        except Exception as e:
            self.logger.error(f'Failed to download pack: {e}')
            return False

        if resp.status_code == 200:
            try:
                zipped = zipfile.ZipFile(io.BytesIO(resp.content))
                for file in [f'pack-{self.latest_commit}.pack', f'pack-{self.latest_commit}.idx']:
                    self.logger.info(f'Unzip {file}')
                    member = zipped.getinfo(file)
                    tmp = self.filepath(f'./objects/pack/{file}.tmp')
                    out = self.filepath(f'./objects/pack/{file}')
                    with zipped.open(member) as source, open(tmp, "wb") as target:
                        shutil.copyfileobj(source, target)
                    os.replace(tmp, out)
                return True
            except zipfile.BadZipFile as e:
                # 文件不是有效的 zip 文件
                self.logger.error(e)
                return False
            except KeyError as e:
                # 归档中不存在该文件
                self.logger.error(e)
                return False
            except Exception as e:
                self.logger.error(e)
                return False
        elif resp.status_code == 404:
            self.logger.error(f'Failed to download pack, status={resp.status_code}, no such pack files provided')
            return False
        else:
            self.logger.error(f'Failed to download pack, status={resp.status_code}, text={resp.text}')
            return False

    def update_refs(self):
        file = self.filepath(f'./refs/remotes/{self.source}/{self.branch}')
        text = f'{self.latest_commit}\n'
        self.logger.info(f'Update refs: {file}')
        os.makedirs(os.path.dirname(file), exist_ok=True)
        try:
            with open(file, 'w', encoding='utf-8', newline='') as f:
                f.write(text)
            return True
        except FileNotFoundError as e:
            self.logger.error(f'Failed to get local commit: {e}')
        except Exception as e:
            self.logger.error(f'Failed to get local commit: {e}')

        return False

    def git_command(self, *args, timeout=300):
        """在子进程中执行 git 命令。

        通常用于拉取或推送大文件。

        Args:
            timeout (int): 超时秒数，默认 300。

        Returns:
            str: 命令的标准输出。
        """
        os.chdir(self.folder)
        cmd = list(map(str, args))
        cmd = [self.git] + cmd
        self.logger.info(f'Execute: {cmd}')

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=False)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            self.logger.warning(f'TimeoutExpired when calling {cmd}, stdout={stdout}, stderr={stderr}')
        return stdout.decode()

    def git_reset(self):
        """执行 git reset --hard 到远程分支。"""
        # 移除 git 锁文件
        for lock_file in [
            './.git/index.lock',
            './.git/HEAD.lock',
            './.git/refs/heads/master.lock',
        ]:
            if os.path.exists(lock_file):
                self.logger.info(f'Lock file {lock_file} exists, removing')
                os.remove(lock_file)
        self.git_command('reset', '--hard', f'{self.source}/{self.branch}')

    def get_status(self):
        """获取仓库状态。

        Returns:
            str: 'uptodate' 表示已是最新，'behind' 表示落后于远程，'failed' 表示获取失败。
        """
        _ = self.current_commit
        _ = self.latest_commit
        if not self.current_commit:
            self.logger.error('Failed to get current commit')
            return 'failed'
        if not self.latest_commit:
            self.logger.error('Failed to get latest commit')
            return 'failed'
        if self.current_commit == self.latest_commit:
            self.logger.info('Already up to date')
            return 'uptodate'
        self.logger.info('Current repo is behind remote')
        return 'behind'

    def update(self):
        """通过 CDN 更新仓库。

        Returns:
            bool: 仓库是否已是最新。
        """
        _ = self.current_commit
        _ = self.latest_commit
        if not self.current_commit:
            self.logger.error('Failed to get current commit')
            return False
        if not self.latest_commit:
            self.logger.error('Failed to get latest commit')
            return False
        if self.current_commit == self.latest_commit:
            self.logger.info('Already up to date')
            self.git_reset()
            return True

        if not self.download_pack():
            return False
        if not self.update_refs():
            return False
        self.git_reset()
        self.logger.info('Update success')
        return True
