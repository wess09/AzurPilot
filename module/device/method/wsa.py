"""WSA（Windows Subsystem for Android）截图和控制后端。
继承 Connection，通过 ADB 连接 WSA 实例进行截图和操作。"""

import re
from functools import partial

from adbutils.errors import AdbError

from module.device.connection import Connection
from module.device.method.retry import retry_backend, recover_adb, recover_unknown
from module.device.method.utils import PackageNotInstalled
from module.logger import logger


def _retry_recover(self, error, trial):
    if isinstance(error, (ConnectionResetError, AdbError)):
        return recover_adb(self, error)
    if isinstance(error, PackageNotInstalled):
        logger.error(error)
        return self.detect_package
    return recover_unknown(error)


retry = partial(retry_backend, recover=_retry_recover, label='设备-WSA')


class WSA(Connection):

    @retry
    def app_current_wsa(self):
        """
        Returns:
            str: 包名。

        Raises:
            OSError
        """
        # 尝试: adb shell dumpsys activity top
        _activityRE = re.compile(
            r'ACTIVITY (?P<package>[^\s]+)/(?P<activity>[^/\s]+) \w+ pid=(?P<pid>\d+)'
        )
        output = self.adb_shell(['dumpsys', 'activity', 'top'])
        ms = _activityRE.finditer(output)
        ret = None
        for m in ms:
            ret = m.group('package')
            if ret == self.package:
                return ret
        if ret:  # get last result
            return ret
        raise OSError("Couldn't get focused app")

    @retry
    def app_start_wsa(self, package_name=None, display=0):
        """
        Args:
            package_name (str):
            display (int):

        Returns:
            bool: 是否成功启动
        """
        if not package_name:
            package_name = self.package
        self.adb_shell(['svc', 'power', 'stayon', 'true'])
        activity_name = self.get_main_activity_name(package_name=package_name)
        result = self.adb_shell(['am', 'start', '--display', display, f'{package_name}/{activity_name}'])
        if 'Activity not started' in result or 'does not exist' in result:
            # Starting: Intent { act=android.intent.action.MAIN cat=[android.intent.category.LAUNCHER] pkg=xxx }
            # Error: Activity not started, unable to resolve Intent { ... }

            # Starting: Intent { act=android.intent.action.MAIN cat=[android.intent.category.LAUNCHER] cmp=com.bilibili.azurlane/xxx }
            # Error type 3
            # Error: Activity class {com.bilibili.azurlane/com.manjuu.azurlane.MainAct} does not exist.
            logger.error(result)
            raise PackageNotInstalled(package_name)
        else:
            # Starting: Intent { act=android.intent.action.MAIN cat=[android.intent.category.LAUNCHER] cmp=.../... }
            return True

    @retry
    def get_main_activity_name(self, package_name=None):
        if not package_name:
            package_name = self.package
        try:
            output = self.adb_shell(['dumpsys', 'package', package_name])
            _activityRE = re.compile(
                r'\w+ ' + package_name + r'/(?P<activity>[^/\s]+) filter'
            )
            ms = _activityRE.finditer(output)
            ret = next(ms).group('activity')
            return ret
        except StopIteration:
            raise PackageNotInstalled(package_name)

    @retry
    def get_display_id(self):
        """
        Returns:
            0: 未找到
            int: 游戏的 display id
        """
        try:
            get_dump_sys_display = str(self.adb_shell(['dumpsys', 'display']))
            display_id_list = re.findall(r'systemapp:' + self.package + ':' + '(.+?)', get_dump_sys_display, re.S)
            display_id = int(display_id_list[0])
            return display_id
        except IndexError:
            return 0  # 当游戏运行在 display 0 上时，其 display id 无法被找到

    @retry
    def display_resize_wsa(self, display):
        logger.warning('display ' + str(display) + ' should be resized')
        self.adb_shell(['wm', 'size', '1280x720', '-d', str(display)])
