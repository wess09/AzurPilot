"""
ADB 截图和输入方法。

通过 Android Debug Bridge (ADB) 执行设备截图和触控操作。
主要提供截图捕获（`screenshot_adb`）、XML 层级获取（`dump_hierarchy`）等方法。
基于 `adb exec-out screencap -p` 命令捕获屏幕图像，
通过 `adb shell input` 命令执行点击、滑动等触控操作。
包含自动重试机制，处理 ADB 连接中断和图像截断等异常情况。
"""
import re
import time
from functools import partial

import cv2
import numpy as np
from adbutils.errors import AdbError
from lxml import etree

from module.base.decorator import Config
from module.config.server import DICT_PACKAGE_TO_ACTIVITY
from module.device.connection import Connection
from module.device.method.retry import retry_backend, recover_adb, recover_truncated_image, recover_unknown
from module.device.method.remove_warning import remove_screenshot_warning
from module.device.method.utils import ImageTruncated, PackageNotInstalled
from module.exception import EmulatorNotRunningError, ScriptError
from module.logger import logger


def _retry_recover(self, error, trial):
    if isinstance(error, (ConnectionResetError, AdbError)):
        return recover_adb(self, error)
    if isinstance(error, PackageNotInstalled):
        logger.error(error)
        return self.detect_package
    if isinstance(error, ImageTruncated):
        return recover_truncated_image(self, error)
    return recover_unknown(error)


retry = partial(retry_backend, recover=_retry_recover, label='设备-ADB')


def load_screencap(data):
    """
    解析 screencap 输出的原始数据为图像。

    Args:
        data: screencap 输出的原始二进制数据。

    Returns:
        解析后的 RGB 图像。
    """
    # 加载数据
    if data is None or len(data) < 12:
        raise ImageTruncated('Empty or incomplete screencap data')

    header = np.frombuffer(data[0:12], dtype=np.uint32)
    channel = 4  # screencap 发送 RGBA 格式图像
    width, height, _ = header  # 通常为 1280, 720, 1

    if data is None or len(data) == 0:
        raise ImageTruncated('Empty image data from screencap')

    image = np.frombuffer(data, dtype=np.uint8)
    if image is None or image.size == 0:
        raise ImageTruncated('Empty image after reading from buffer')

    try:
        image = image[-int(width * height * channel):].reshape(height, width, channel)
    except ValueError as e:
        # ValueError: cannot reshape array of size 0 into shape (720,1280,4)
        raise ImageTruncated(str(e))

    image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)
    if image is None:
        raise ImageTruncated('Empty image after cv2.cvtColor')

    return image


class Adb(Connection):
    __screenshot_method = [0, 1, 2]
    __screenshot_method_fixed = [0, 1, 2]

    @staticmethod
    def __load_screenshot(screenshot, method):
        if method == 0:
            pass
        elif method == 1:
            screenshot = screenshot.replace(b'\r\n', b'\n')
        elif method == 2:
            screenshot = screenshot.replace(b'\r\r\n', b'\n')
        else:
            raise ScriptError(f'Unknown method to load screenshots: {method}')

        screenshot = remove_screenshot_warning(screenshot)

        if screenshot is None or len(screenshot) == 0:
            raise ImageTruncated('Empty screenshot payload in __load_screenshot')

        image = np.frombuffer(screenshot, np.uint8)
        if image is None or image.size == 0:
            raise ImageTruncated('Empty image after reading from buffer')

        image = cv2.imdecode(image, cv2.IMREAD_COLOR)
        if image is None:
            raise ImageTruncated('Empty image after cv2.imdecode')

        cv2.cvtColor(image, cv2.COLOR_BGR2RGB, dst=image)
        if image is None:
            raise ImageTruncated('Empty image after cv2.cvtColor')

        return image

    def __process_screenshot(self, screenshot):
        for method in self.__screenshot_method_fixed:
            try:
                result = self.__load_screenshot(screenshot, method=method)
                self.__screenshot_method_fixed = [method] + self.__screenshot_method
                return result
            except (OSError, ImageTruncated):
                continue

        self.__screenshot_method_fixed = self.__screenshot_method
        if len(screenshot) < 500:
            logger.warning(f'[设备-ADB] 异常截图: {screenshot}')
        raise OSError(f'cannot load screenshot')

    @retry(on_exhausted=EmulatorNotRunningError)
    @Config.when(DEVICE_OVER_HTTP=False)
    def screenshot_adb(self):
        data = self.adb_shell(['screencap', '-p'], stream=True)
        if len(data) < 500:
            logger.warning(f'[设备-ADB] 异常截图: {data}')

        return self.__process_screenshot(data)

    @retry(on_exhausted=EmulatorNotRunningError)
    @Config.when(DEVICE_OVER_HTTP=True)
    def screenshot_adb(self):
        data = self.adb_shell(['screencap'], stream=True)
        data = remove_screenshot_warning(data)
        if len(data) < 500:
            logger.warning(f'[设备-ADB] 异常截图: {data}')

        return load_screencap(data)

    @retry(on_exhausted=EmulatorNotRunningError)
    def screenshot_adb_nc(self):
        data = self.adb_shell_nc(['screencap'])
        data = remove_screenshot_warning(data)
        if len(data) < 500:
            logger.warning(f'[设备-ADB] 异常截图: {data}')

        return load_screencap(data)

    @retry
    def click_adb(self, x, y):
        start = time.time()
        self.adb_shell(['input', 'tap', x, y])
        if time.time() - start <= 0.05:
            self.sleep(0.05)

    @retry
    def swipe_adb(self, p1, p2, duration=0.1):
        duration = int(duration * 1000)
        self.adb_shell(['input', 'swipe', *p1, *p2, duration])

    @retry
    def app_current_adb(self):
        """
        获取当前前台应用的包名，复制自 uiautomator2。

        Returns:
            当前前台应用的包名。

        Raises:
            OSError: 无法获取前台应用时抛出。

        Note:
            reset_uiautomator 函数依赖此方法，因此不能在此使用 jsonrpc。
        """
        # 相关 issue: https://github.com/openatx/uiautomator2/issues/200
        # $ adb shell dumpsys window windows
        # 输出示例:
        #   mCurrentFocus=Window{41b37570 u0 com.incall.apps.launcher/com.incall.apps.launcher.Launcher}
        #   mFocusedApp=AppWindowToken{422df168 token=Token{422def98 ActivityRecord{422dee38 u0 com.example/.UI.play.PlayActivity t14}}}
        # 正则表达式
        #   r'mFocusedApp=.*ActivityRecord{\w+ \w+ (?P<package>.*)/(?P<activity>.*) .*'
        #   r'mCurrentFocus=Window{\w+ \w+ (?P<package>.*)/(?P<activity>.*)\}')
        _focusedRE = re.compile(
            r'mCurrentFocus=Window{.*\s+(?P<package>[^\s]+)/(?P<activity>[^\s]+)\}'
        )
        m = _focusedRE.search(self.adb_shell(['dumpsys', 'window', 'windows']))
        if m:
            return m.group('package')

        # 尝试: adb shell dumpsys activity top
        _activityRE = re.compile(
            r'ACTIVITY (?P<package>[^\s]+)/(?P<activity>[^/\s]+) \w+ pid=(?P<pid>\d+)'
        )
        output = self.adb_shell(['dumpsys', 'activity', 'top'])
        ms = _activityRE.finditer(output)
        ret = None
        for m in ms:
            ret = m.group('package')
        if ret:  # 取最后一个结果
            return ret
        raise OSError("Couldn't get focused app")

    @retry(on_exhausted=EmulatorNotRunningError)
    def _app_start_adb_monkey(self, package_name=None, allow_failure=False):
        """
        通过 monkey 命令启动应用。

        Args:
            package_name: 应用包名，默认从配置获取。
            allow_failure: 为 True 时不抛出 PackageNotInstalled 异常，直接返回 False。

        Returns:
            是否成功启动。

        Raises:
            PackageNotInstalled: 应用未安装且 allow_failure 为 False 时抛出。
        """
        if not package_name:
            package_name = self.package
        result = self.adb_shell([
            'monkey', '-p', package_name, '-c',
            'android.intent.category.LAUNCHER', '--pct-syskeys', '0', '1'
        ])
        if 'No activities found' in result:
            # ** No activities found to run, monkey aborted.
            if allow_failure:
                return False
            else:
                logger.error(result)
                raise PackageNotInstalled(package_name)
        elif 'inaccessible' in result:
            # /system/bin/sh: monkey: inaccessible or not found
            return False
        else:
            # Events injected: 1
            # ## Network stats: elapsed time=4ms (0ms mobile, 0ms wifi, 4ms not connected)
            return True

    @retry(on_exhausted=EmulatorNotRunningError)
    def _app_start_adb_am(self, package_name=None, activity_name=None, allow_failure=False):
        """
        通过 am start 命令启动应用。

        Args:
            package_name: 应用包名，默认从配置获取。
            activity_name: Activity 名称，默认从 DICT_PACKAGE_TO_ACTIVITY 获取。
            allow_failure: 为 True 时不抛出 PackageNotInstalled 异常，直接返回 False。

        Returns:
            是否成功启动。

        Raises:
            PackageNotInstalled: 应用未安装且 allow_failure 为 False 时抛出。
        """
        if not package_name:
            package_name = self.package
        if not activity_name:
            result = self.adb_shell(['dumpsys', 'package', package_name])
            res = re.search(r'android.intent.action.MAIN:\s+\w+ ([\w.\/]+) filter \w+\s+'
                            r'.*\s+Category: "android.intent.category.LAUNCHER"',
                            result)
            if res:
                # com.bilibili.azurlane/com.manjuu.azurlane.MainActivity
                activity_name = res.group(1)
                try:
                    activity_name = activity_name.split('/')[-1]
                except IndexError:
                    logger.error(f'无Activity名称 {activity_name}')
                    return False
            else:
                if allow_failure:
                    return False
                else:
                    logger.error(result)
                    raise PackageNotInstalled(package_name)

        cmd = ['am', 'start', '-a', 'android.intent.action.MAIN', '-c',
               'android.intent.category.LAUNCHER', '-n', f'{package_name}/{activity_name}']
        if self.is_local_network_device and self.is_waydroid:
            cmd += ['--windowingMode', '4']
        ret = self.adb_shell(cmd)
        # 无效 Activity
        # Starting: Intent { act=android.intent.action.MAIN cat=[android.intent.category.LAUNCHER] cmp=... }
        # Error type 3
        # Error: Activity class {.../...} does not exist.
        if 'Error: Activity class' in ret:
            if allow_failure:
                return False
            else:
                logger.error(ret)
                return False
        # 已在运行
        # Warning: Activity not started, intent has been delivered to currently running top-most instance.
        if 'Warning: Activity not started' in ret:
            logger.info('应用Activity已启动')
            return True
        # 权限拒绝
        # Starting: Intent { act=android.intent.action.MAIN cat=[android.intent.category.LAUNCHER] cmp=com.YoStarEN.AzurLane/com.manjuu.azurlane.MainActivity }
        # java.lang.SecurityException: Permission Denial: ...
        if 'Permission Denial' in ret:
            if allow_failure:
                return False
            else:
                logger.error(ret)
                logger.error('[设备-ADB] Permission Denial while starting app, probably because activity invalid')
                return False
        # 启动成功
        # Starting: Intent...
        return True

    # 不使用 @retry 装饰器，因为 _app_start_adb_am 和 _app_start_adb_monkey 已经有 @retry
    # @retry
    def app_start_adb(self, package_name=None, activity_name=None, allow_failure=False):
        """
        启动应用，依次尝试 am start 和 monkey 方式。

        Args:
            package_name: 应用包名，为 None 时从配置获取。
            activity_name: Activity 名称，为 None 时从 DICT_PACKAGE_TO_ACTIVITY 获取，
                仍为 None 时通过 monkey 启动，monkey 失败后再通过 am 启动。
            allow_failure: 为 True 时不抛出 PackageNotInstalled 异常，直接返回 False。

        Returns:
            是否成功启动。

        Raises:
            PackageNotInstalled: 应用未安装且 allow_failure 为 False 时抛出。
        """
        if not package_name:
            package_name = self.package
        if not activity_name:
            activity_name = DICT_PACKAGE_TO_ACTIVITY.get(package_name)

        if activity_name:
            if self._app_start_adb_am(package_name, activity_name, allow_failure):
                return True
        if self._app_start_adb_monkey(package_name, allow_failure):
            return True
        if self._app_start_adb_am(package_name, activity_name, allow_failure):
            return True

        logger.error('所有尝试失败')
        return False

    @retry
    def app_stop_adb(self, package_name=None):
        """停止应用：am force-stop。"""
        if not package_name:
            package_name = self.package
        self.adb_shell(['am', 'force-stop', package_name])

    @retry
    def dump_hierarchy_adb(self, temp: str = '/data/local/tmp/hierarchy.xml') -> etree._Element:
        """
        通过 uiautomator dump 导出 UI 层级结构。

        Args:
            temp: 模拟器上的临时文件路径。

        Returns:
            解析后的 XML 层级结构。
        """
        # 删除已有文件
        # self.adb_shell(['rm', '/data/local/tmp/hierarchy.xml'])

        # 导出层级结构
        for _ in range(2):
            response = self.adb_shell(['uiautomator', 'dump', '--compressed', temp])
            if 'hierchary' in response:
                # UI hierchary dumped to: /data/local/tmp/hierarchy.xml
                break
            else:
                # <None>
                # 必须终止 uiautomator2
                self.app_stop_adb('com.github.uiautomator')
                self.app_stop_adb('com.github.uiautomator.test')
                continue

        # 从设备读取
        content = b''
        for chunk in self.adb.sync.iter_content(temp):
            if chunk:
                content += chunk
            else:
                break

        # 使用 lxml 解析
        hierarchy = etree.fromstring(content)
        return hierarchy
