import json
import multiprocessing
import os
import zipfile
from multiprocessing import queues, Process
from shutil import rmtree
from typing import Union
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.request import Request

from .asst import Asst
from .utils import Version


class Updater:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/97.0.4692.99 '
                      'Safari/537.36 '
                      'Edg/97.0.1072.76'
    }
    RequestUrl = "repos/MaaAssistantArknights/MaaRelease/releases"
    StableRequestUrl = "repos/MaaAssistantArknights/MaaAssistantArknights/releases/latest"
    MaaReleaseRequestUrlByTag = "repos/MaaAssistantArknights/MaaRelease/releases/tags/"
    InfoRequestUrl = "repos/MaaAssistantArknights/MaaAssistantArknights/releases/tags/"

    @staticmethod
    def custom_print(s):
        """可被 monkey patch 的打印函数。

        在其他 GUI 上使用时可以替换为任意需要的输出方式。
        """
        print(s)

    @staticmethod
    def _get_cur_version(path, q):
        """在子进程中获取当前 MAA 版本号。

        Args:
            path: MAA 安装路径。
            q: 用于传递版本号的队列。
        """
        Asst.load(path=path)
        q.put(Asst().get_version())

    def __init__(self, path, version):
        """初始化更新器并获取当前版本信息。

        Args:
            path: MAA 安装路径。
            version: 目标更新版本类型（Stable/Beta/Nightly）。
        """
        self.path = path
        self.version = version
        self.latest_json = None
        self.latest_version = None
        self.assets_object = None

        # 使用子进程获取当前版本后关闭，避免占用 DLL
        q = queues.Queue(1, ctx=multiprocessing)
        p = Process(target=self._get_cur_version, args=(path, q,))
        p.start()
        p.join()
        self.cur_version = q.get()

    @staticmethod
    def _request_github_api(url, retry):
        request_resource = ["https://api.github.com/", "https://api.kgithub.com/"]
        for _ in range(retry):
            for resource in request_resource:
                try:
                    response = request.urlopen(Request(url=resource + url, headers=Updater.headers), timeout=20)
                    data = response.read().decode('utf-8')
                    Updater.custom_print(f'访问成功，URL: {resource + url}')
                    return data
                except (HTTPError, URLError) as e:
                    Updater.custom_print(f'访问成功，URL: {resource + url}')
                    Updater.custom_print(e)
                    if _ == retry - 1:
                        raise

    def _is_nightly_version(self, ver: Union[str, None]):
        """判断版本号是否为 Nightly 构建。

        Args:
            ver: 版本号字符串，为 None 时使用当前版本。

        Returns:
            bool: 是否为 Nightly 版本。
        """
        if ver is None:
            ver = self.cur_version

        if '-' not in ver:
            return False
        last_id = ver.split('.')[-1]
        return last_id.startswith('g') and len(last_id) >= 7

    def _is_std_version(self, ver: Union[str, None]):
        """判断版本号是否为标准发布版本。

        排除 DEBUG、本地构建和 Nightly 版本。

        Args:
            ver: 版本号字符串，为 None 时使用当前版本。

        Returns:
            bool: 是否为标准版本。
        """
        if ver is None:
            ver = self.cur_version

        if ver == 'DEBUG VERSION':
            return False
        elif ver.startswith('c') or ver.startswith('20') or 'local' in ver:
            return False
        elif self._is_nightly_version(ver):
            return False
        return True

    @staticmethod
    def _split_version(ver: str):
        """将版本号字符串解析为可比较的整数列表。

        支持标准版本和预发布版本（alpha、beta、rc）的解析。

        Args:
            ver: 版本号字符串，如 v4.2.0-beta.1。

        Returns:
            list: 解析后的整数列表。
        """
        if '-' in ver:
            pre, sub = ver.split('-', 1)
        else:
            pre = ver
            sub = None
        pre = pre.split('.')
        pre[0] = pre[0][1:]
        if sub:
            sub = sub.split('.')
            sub = sub[:-1]
            if sub[0] == 'alpha':
                sub[0] = '1'
            elif sub[0] == 'beta':
                sub[0] = '2'
            elif sub[0] == 'rc':
                sub[0] = '3'
            out = pre + sub
        else:
            out = pre
        for i in range(len(out)):
            out[i] = int(out[i])
        return out

    @staticmethod
    def _compare_version(a, b):
        """比较两个版本号的大小。

        Args:
            a: 第一个版本号字符串。
            b: 第二个版本号字符串。

        Returns:
            bool: 如果 a < b 则返回 True，否则返回 False。
        """
        a = Updater._split_version(a)
        b = Updater._split_version(b)
        for i in range(len(a)):
            try:
                if a[i] < b[i]:
                    return True
                elif a[i] > b[i]:
                    return False
            except IndexError:
                return False
        if len(b) > len(a):
            return True
        return False

    def _check_update(self):
        """检查是否有可用更新。

        根据目标版本类型（Stable/Beta/Nightly）查询 GitHub API，
        比较版本号并查找可用的 OTA 更新包。

        Returns:
            bool: 是否有可用更新。
        """
        max_retry = 2
        if self.version == Version.Stable:
            stable_response = self._request_github_api(self.StableRequestUrl, max_retry)
            if len(stable_response) == 0:
                raise HTTPError

            self.latest_json = json.loads(stable_response)
            self.latest_version = self.latest_json['tag_name']

            stable_response = self._request_github_api(self.MaaReleaseRequestUrlByTag + self.latest_version, max_retry)
            if len(stable_response) == 0:
                return False
            self.latest_json = json.loads(stable_response)
        else:
            response = self._request_github_api(self.RequestUrl, max_retry)
            if len(response) == 0:
                raise HTTPError
            release_array = json.loads(response)
            self.latest_json = None
            for item in release_array:
                if not self.version == Version.Nightly and not self._is_std_version(item['tag_name']):
                    continue
                self.latest_json = item
                break

        if self.latest_json is None:
            return False
        self.latest_version = self.latest_json['tag_name']
        release_assets = self.latest_json['assets']

        if self.version == Version.Nightly and self.cur_version == self.latest_version:
            return False
        elif not self._compare_version(self.cur_version, self.latest_version):
            return False

        if self._is_std_version(self.latest_version):
            info_responce = self._request_github_api(self.InfoRequestUrl + self.latest_version, max_retry)
            if len(info_responce) == 0:
                raise HTTPError
            self.latest_json = json.loads(info_responce)

        for cur_assets in release_assets:
            name = cur_assets['name'].lower()
            if 'ota' in name and 'win' in name and f'{self.cur_version}_{self.latest_version}' in name:
                self.assets_object = cur_assets
                break
        return True

    def _remove_file(self):
        """清理更新过程中产生的临时文件。

        读取 removelist.txt 中的文件列表并删除，同时清理 md5sum.txt 和 OTA 包。
        """
        def remove_with_print(s):
            self.custom_print(f'删除文件：{s}')
            os.remove(s)

        removelist_path = os.path.join(self.path, 'removelist.txt')
        if os.path.isfile(removelist_path):
            with open(removelist_path, 'r') as f:
                file_list = f.readlines()
                for file in file_list:
                    file_path = os.path.join(self.path, file)
                    if os.path.isfile(file_path):
                        remove_with_print(file_path)
                    elif os.path.isdir(file_path):
                        self.custom_print(f'删除文件夹：{file_path}')
                        rmtree(file_path)
                f.close()
            remove_with_print(removelist_path)

        md5sum_path = os.path.join(self.path, 'md5sum.txt')
        if os.path.isfile(md5sum_path):
            remove_with_print(md5sum_path)
        for file in os.listdir(self.path):
            if 'OTA' in file:
                file_path = os.path.join(self.path, file)
                remove_with_print(file_path)

    def update(self):
        """执行 MAA 的自动更新流程。

        包含检查更新、下载 OTA 包、解压安装和清理临时文件四个步骤。

        Returns:
            bool: 是否成功更新，无需更新时返回 False。
        """
        max_retry = 3
        if not self._check_update():
            Updater.custom_print('目前不需要更新')
            return False

        # 下载
        replace_list = [
            ('github.com', 'ota.maa.plus'),
            ('github.com', 'download.fastgit.org')
        ]
        for i in range(max_retry):
            url = self.assets_object['browser_download_url']
            file = os.path.join(self.path, url.split('/')[-1])
            if i < 2:
                url = url.replace(replace_list[i][0], replace_list[i][1])
                try:
                    Updater.custom_print(f'开始下载更新包，URL：{url}')
                    request.urlretrieve(url, file)
                    break
                except (HTTPError, URLError) as e:
                    Updater.custom_print(e)

        # 解压
        Updater.custom_print('开始安装更新，请不要关闭')
        zfile = zipfile.ZipFile(file, 'r')
        zfile.extractall(self.path)
        zfile.close()

        # 清理临时文件
        self._remove_file()

        Updater.custom_print('更新完成')
