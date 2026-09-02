# 此文件实现了基于 uiautomator2 的设备交互逻辑。
# 包含截图、模拟点击、长按、滑动、层级提取（dump）等控制移动端设备的核心操作。
import base64
import time
import typing as t
from dataclasses import dataclass
from functools import wraps
from json.decoder import JSONDecodeError
from subprocess import list2cmdline

import uiautomator2 as u2
from adbutils.errors import AdbError
from lxml import etree

from module.base.utils import *
from module.config.server import DICT_PACKAGE_TO_ACTIVITY
from module.device.connection import Connection
from module.device.method.utils import (ImageTruncated, PackageNotInstalled, RETRY_TRIES, handle_adb_error,
                                        handle_unknown_host_service, possible_reasons, retry_sleep)
from module.exception import EmulatorNotRunningError, RequestHumanTakeover
from module.logger import logger


def retry(func):
    @wraps(func)
    def retry_wrapper(self, *args, **kwargs):
        """
        Args:
            self (Uiautomator2):
        """
        init = None
        for _ in range(RETRY_TRIES):
            try:
                if callable(init):
                    time.sleep(retry_sleep(_))
                    init()
                return func(self, *args, **kwargs)
            # 不可处理
            except RequestHumanTakeover:
                break
            # adb server 被终止时
            except ConnectionResetError as e:
                logger.error(e)

                def init():
                    self.adb_reconnect()
            # 在 `device.set_new_command_timeout(604800)` 时
            # json.decoder.JSONDecodeError: Expecting value: line 1 column 2 (char 1)
            except JSONDecodeError as e:
                logger.error(e)

                def init():
                    self.install_uiautomator2()
            # AdbError
            except AdbError as e:
                if handle_adb_error(e):
                    def init():
                        self.adb_reconnect()
                elif handle_unknown_host_service(e):
                    def init():
                        self.adb_start_server()
                        self.adb_reconnect()
                else:
                    break
            # RuntimeError: USB device 127.0.0.1:5555 is offline
            except RuntimeError as e:
                if handle_adb_error(e):
                    def init():
                        self.adb_reconnect()
                else:
                    break
            # 在 `assert c.read string(4) == _OKAY` 时
            # 模拟器未启用 ADB
            except AssertionError as e:
                logger.exception(e)
                possible_reasons(
                    '如果你使用的是 BlueStacks、雷电模拟器或 WSA，'
                    '请在模拟器设置中启用 ADB'
                )
                break
            # 包未安装
            except PackageNotInstalled as e:
                logger.error(e)

                def init():
                    self.detect_package()
            # 图像截断
            except ImageTruncated as e:
                from module.device.method.utils import handle_image_truncated
                handle_image_truncated(self, e)

                def init():
                    pass
            # 不可处理 - 必须向上抛出以触发模拟器重启
            except EmulatorNotRunningError:
                raise
            # 未知异常
            except Exception as e:
                logger.exception(e)

                def init():
                    pass

        if func.__name__ in [
            '_app_start_u2_am', '_app_start_u2_monkey',
            'screenshot_uiautomator2',
            'app_current_uiautomator2',
            'app_stop_uiautomator2',
        ]:
            # 这些函数失败说明设备连接已断开，应触发重启而非人工介入
            # app_stop_uiautomator2 失败属于应用重启失败，按项目规则
            # 必须抛 EmulatorNotRunningError 触发模拟器重启，
            # 而非 RequestHumanTakeover（会被错误地视为不可恢复）
            logger.critical(f'[设备-U2] 重试 {func.__name__}() 失败')
            raise EmulatorNotRunningError

        logger.critical(f'[设备-U2] 重试 {func.__name__}() 失败')
        raise RequestHumanTakeover

    return retry_wrapper


@dataclass
class ProcessInfo:
    pid: int
    ppid: int
    thread_count: int
    cmdline: str
    name: str


@dataclass
class ShellBackgroundResponse:
    success: bool
    pid: int
    description: str


class Uiautomator2(Connection):
    @retry
    def screenshot_uiautomator2(self):
        image = self.u2.screenshot(format='raw')
        # 防止 None/空响应
        if image is None or len(image) == 0:
            raise ImageTruncated('Empty image content from uiautomator2')

        image = np.frombuffer(image, np.uint8)
        if image is None or image.size == 0:
            raise ImageTruncated('Empty image after reading from buffer')

        image = cv2.imdecode(image, cv2.IMREAD_COLOR)
        if image is None:
            raise ImageTruncated('Empty image after cv2.imdecode')

        cv2.cvtColor(image, cv2.COLOR_BGR2RGB, dst=image)
        if image is None:
            raise ImageTruncated('Empty image after cv2.cvtColor')

        return image

    @retry
    def click_uiautomator2(self, x, y):
        self.u2.click(x, y)

    @retry
    def long_click_uiautomator2(self, x, y, duration=(1, 1.2)):
        self.u2.long_click(x, y, duration=duration)

    @retry
    def swipe_uiautomator2(self, p1, p2, duration=0.1):
        self.u2.swipe(*p1, *p2, duration=duration)

    @retry
    def _drag_along(self, path):
        """沿路径滑动。

        Args:
            path (list): (x, y, sleep)

        Examples:
            al.drag_along([
                (403, 421, 0.2),
                (821, 326, 0.1),
                (821, 326-10, 0.1),
                (821, 326+10, 0.1),
                (821, 326, 0),
            ])
            等价于:
            al.device.touch.down(403, 421)
            time.sleep(0.2)
            al.device.touch.move(821, 326)
            time.sleep(0.1)
            al.device.touch.move(821, 326-10)
            time.sleep(0.1)
            al.device.touch.move(821, 326+10)
            time.sleep(0.1)
            al.device.touch.up(821, 326)
        """
        length = len(path)
        for index, data in enumerate(path):
            x, y, second = data
            if index == 0:
                self.u2.touch.down(x, y)
                logger.info(point2str(x, y) + ' 按下')
            elif index - length == -1:
                self.u2.touch.up(x, y)
                logger.info(point2str(x, y) + ' 抬起')
            else:
                self.u2.touch.move(x, y)
                logger.info(point2str(x, y) + ' 移动')
            self.sleep(second)

    def drag_uiautomator2(self, p1, p2, segments=1, shake=(0, 15), point_random=(-10, -10, 10, 10),
                          shake_random=(-5, -5, 5, 5), swipe_duration=0.25, shake_duration=0.1,
                          hold_duration=0.0):
        """拖拽并抖动，示意如下:
                     /\
        +-----------+  +  +
                        \/
        简单的滑动或拖拽效果不佳，因为只有两个点。
        添加一些路径点使其更像真实滑动。

        Args:
            p1 (tuple): 起始点，(x, y)。
            p2 (tuple): 终止点，(x, y)。
            segments (int):
            shake (tuple): 到达终止点后的抖动。
            point_random: 为起始点和终止点添加随机偏移。
            shake_random: 为抖动数组添加随机偏移。
            swipe_duration: 路径点之间的间隔时间。
            shake_duration: 抖动点之间的间隔时间。
            hold_duration: 松开前的持续按住时间。
        """
        p1 = np.array(p1) - random_rectangle_point(point_random)
        p2 = np.array(p2) - random_rectangle_point(point_random)
        path = [(x, y, swipe_duration) for x, y in random_line_segments(p1, p2, n=segments, random_range=point_random)]
        path += [
            (*p2 + shake + random_rectangle_point(shake_random), shake_duration),
            (*p2 - shake - random_rectangle_point(shake_random), shake_duration),
            (*p2, shake_duration)
        ]
        internal_hold = ensure_time(shake_duration) * 3
        hold_duration = ensure_time(hold_duration) - internal_hold
        if hold_duration > 0:
            path += [
                (*p2, hold_duration),
                (*p2, 0),
            ]
        path = [(int(x), int(y), d) for x, y, d in path]
        self._drag_along(path)

    @retry
    def app_current_uiautomator2(self):
        """
        Returns:
            str: 包名。
        """
        result = self.u2.app_current()
        return result['package']

    @retry
    def _app_start_u2_monkey(self, package_name=None, allow_failure=False):
        """
        Args:
            package_name (str):
            allow_failure (bool):

        Returns:
            bool: 是否成功启动

        Raises:
            PackageNotInstalled:
        """
        if not package_name:
            package_name = self.package
        result = self.u2.shell([
            'monkey', '-p', package_name, '-c',
            'android.intent.category.LAUNCHER', '--pct-syskeys', '0', '1'
        ])
        if 'No activities found' in result.output:
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

    @retry
    def _app_start_u2_am(self, package_name=None, activity_name=None, allow_failure=False):
        """
        Args:
            package_name (str):
            activity_name (str):
            allow_failure (bool):

        Returns:
            bool: 是否成功启动

        Raises:
            PackageNotInstalled:
        """
        if not package_name:
            package_name = self.package
        if not activity_name:
            try:
                info = self.u2.app_info(package_name)
            except u2.BaseError as e:
                if allow_failure:
                    return False
                # BaseError('package "111" not found')
                elif 'not found' in str(e):
                    logger.error(e)
                    raise PackageNotInstalled(package_name)
                # 未知错误
                else:
                    raise
            activity_name = info['mainActivity']

        cmd = ['am', 'start', '-a', 'android.intent.action.MAIN', '-c',
               'android.intent.category.LAUNCHER', '-n', f'{package_name}/{activity_name}']
        if self.is_local_network_device and self.is_waydroid:
            cmd += ['--windowingMode', '4']
        ret = self.u2.shell(cmd)
        # 无效的 activity
        # Starting: Intent { act=android.intent.action.MAIN cat=[android.intent.category.LAUNCHER] cmp=... }
        # Error type 3
        # Error: Activity class {.../...} does not exist.
        if 'Error: Activity class' in ret.output:
            if allow_failure:
                return False
            else:
                logger.error(ret)
                return False
        # 已在运行
        # Warning: Activity not started, intent has been delivered to currently running top-most instance.
        if 'Warning: Activity not started' in ret.output:
            logger.info('应用Activity已启动')
            return True
        # Starting: Intent { act=android.intent.action.MAIN cat=[android.intent.category.LAUNCHER] cmp=com.YoStarEN.AzurLane/com.manjuu.azurlane.MainActivity }
        # java.lang.SecurityException: Permission Denial: starting Intent { act=android.intent.action.MAIN cat=[android.intent.category.LAUNCHER] flg=0x10000000 cmp=com.YoStarEN.AzurLane/com.manjuu.azurlane.MainActivity } from null (pid=5140, uid=2000) not exported from uid 10064
        #         at android.os.Parcel.readException(Parcel.java:1692)
        #         at android.os.Parcel.readException(Parcel.java:1645)
        #         at android.app.ActivityManagerProxy.startActivityAsUser(ActivityManagerNative.java:3152)
        #         at com.android.commands.am.Am.runStart(Am.java:643)
        #         at com.android.commands.am.Am.onRun(Am.java:394)
        #         at com.android.internal.os.BaseCommand.run(BaseCommand.java:51)
        #         at com.android.commands.am.Am.main(Am.java:124)
        #         at com.android.internal.os.RuntimeInit.nativeFinishInit(Native Method)
        #         at com.android.internal.os.RuntimeInit.main(RuntimeInit.java:290)
        if 'Permission Denial' in ret.output:
            if allow_failure:
                return False
            else:
                logger.error(ret)
                logger.error('启动应用时权限拒绝，可能Activity无效')
                return False
        # 成功
        # Starting: Intent...
        return True

    # 不使用 @retry 装饰器，因为 _app_start_adb_am 和 _app_start_adb_monkey 已有 @retry
    # @retry
    def app_start_uiautomator2(self, package_name=None, activity_name=None, allow_failure=False):
        """
        Args:
            package_name (str):
                为 None 时从配置中获取
            activity_name (str):
                为 None 时从 DICT_PACKAGE_TO_ACTIVITY 获取
                仍为 None 时通过 monkey 启动
                monkey 失败时，获取 activity 名称并通过 am 启动
            allow_failure (bool):
                为 True 时不抛出 PackageNotInstalled，只返回 False

        Returns:
            bool: 是否成功启动

        Raises:
            PackageNotInstalled:
        """
        if not package_name:
            package_name = self.package
        if not activity_name:
            activity_name = DICT_PACKAGE_TO_ACTIVITY.get(package_name)

        if activity_name:
            if self._app_start_u2_am(package_name, activity_name, allow_failure):
                return True
        if self._app_start_u2_monkey(package_name, allow_failure):
            return True
        if self._app_start_u2_am(package_name, activity_name, allow_failure):
            return True

        logger.error('[设备-U2] 所有尝试失败')
        return False

    @retry
    def app_stop_uiautomator2(self, package_name=None):
        if not package_name:
            package_name = self.package
        self.u2.app_stop(package_name)

    @retry
    def dump_hierarchy_uiautomator2(self) -> etree._Element:
        content = self.u2.dump_hierarchy(compressed=False)
        # print(content)
        hierarchy = etree.fromstring(content.encode('utf-8'))
        return hierarchy

    def uninstall_uiautomator2(self):
        logger.info('[设备-U2] 移除uiautomator2')
        for file in [
            'app-uiautomator.apk',
            'app-uiautomator-test.apk',
            'minitouch',
            'minitouch.so',
            'atx-agent',
        ]:
            self.adb_shell(["rm", f"/data/local/tmp/{file}"])

    @retry
    def resolution_uiautomator2(self, cal_rotation=True) -> t.Tuple[int, int]:
        """
        获取设备的有效分辨率，优先通过 ADB wm size 获取（支持 wm size override），
        回退到 uiautomator2 /info 接口。

        当用户通过 `adb shell wm size 720x1280` 设置了覆盖分辨率时，
        uiautomator2 /info 接口仍返回物理分辨率（如 1080x2400），
        而 ADB wm size 能正确报告 Override size。

        Returns:
            (width, height)
        """
        # 优先使用 ADB wm size，支持 override 分辨率
        lines = []
        result = ''
        try:
            result = self.adb_shell(['wm', 'size'])
            lines = result.strip().split('\n')
        except Exception:
            logger.warning('[设备-U2] 执行adb shell wm size失败，回退到u2 /info')

        if lines:
            w, h = None, None
            import re
            size_pattern = re.compile(r'^(\d+)x(\d+)$')

            # 优先读取 Override size（用户通过 wm size 设置的值）
            for line in lines:
                line = line.strip()
                if 'Override size:' in line:
                    try:
                        size_str = line.split(':', 1)[1].strip()
                        m = size_pattern.match(size_str)
                        if m:
                            w, h = int(m.group(1)), int(m.group(2))
                            break
                    except (ValueError, IndexError):
                        continue

            if w is None:
                # 没有 Override，尝试 Physical size 行或裸分辨率行
                for line in lines:
                    line = line.strip()
                    try:
                        if 'Physical size:' in line:
                            size_str = line.split(':', 1)[1].strip()
                            m = size_pattern.match(size_str)
                            if m:
                                w, h = int(m.group(1)), int(m.group(2))
                                break
                        elif size_pattern.match(line):
                            # 旧版 Android 仅输出 "1080x2400"
                            m = size_pattern.match(line)
                            if m:
                                w, h = int(m.group(1)), int(m.group(2))
                                break
                    except (ValueError, IndexError):
                        continue

            if w is not None and h is not None:
                if cal_rotation:
                    rotation = self.get_orientation()
                    if (w > h) != (rotation % 2 == 1):
                        w, h = h, w
                return w, h

            logger.warning(
                'Failed to parse resolution from ADB wm size, fallback to u2 /info. '
                f'Raw output: {result!r}'
            )

        # 回退到 uiautomator2 /info 接口
        info = self.u2.http.get('/info').json()
        w, h = info['display']['width'], info['display']['height']
        if cal_rotation:
            rotation = self.get_orientation()
            if (w > h) != (rotation % 2 == 1):
                w, h = h, w
        return w, h

    def resolution_check_uiautomator2(self):
        """
        Alas 不主动检查分辨率，而是检查截图的宽高。
        但某些截图方法不提供设备分辨率，因此在此处进行检查。

        Returns:
            (width, height)

        Raises:
            RequestHumanTakeover: 分辨率不是 1280x720 时抛出
        """
        width, height = self.resolution_uiautomator2()
        logger.attr('屏幕尺寸', f'{width}x{height}')
        if width == 1280 and height == 720:
            return (width, height)
        if width == 720 and height == 1280:
            return (width, height)

        logger.critical(f"[设备-U2] 大叔，你看着分辨率对吗: {width}x{height}。真是个连分辨率都不会设的杂鱼呢❤")
        logger.critical("[设备-U2] 乖乖给我改成 1280x720 哦，不然我可不理你了❤")
        raise RequestHumanTakeover

    @retry
    def proc_list_uiautomator2(self) -> t.List[ProcessInfo]:
        """
        获取当前进程信息。
        """
        resp = self.u2.http.get("/proc/list", timeout=10)
        resp.raise_for_status()
        result = [
            ProcessInfo(
                pid=proc['pid'],
                ppid=proc['ppid'],
                thread_count=proc['threadCount'],
                cmdline=' '.join(proc['cmdline']) if proc['cmdline'] is not None else '',
                name=proc['name'],
            ) for proc in resp.json()
        ]
        return result

    @retry
    def u2_shell_background(self, cmdline, timeout=10) -> ShellBackgroundResponse:
        """
        在后台运行命令。

        注意此函数总是返回成功响应，
        因为这是 ATX 中一个未经测试的隐藏方法。
        """
        if isinstance(cmdline, (list, tuple)):
            cmdline = list2cmdline(cmdline)
        elif isinstance(cmdline, str):
            cmdline = cmdline
        else:
            raise TypeError("cmdargs type invalid", type(cmdline))

        data = dict(command=cmdline, timeout=str(timeout))
        ret = self.u2.http.post("/shell/background", data=data, timeout=timeout + 10)
        ret.raise_for_status()

        resp = ret.json()
        resp = ShellBackgroundResponse(
            success=bool(resp.get('success', False)),
            pid=resp.get('pid', 0),
            description=resp.get('description', '')
        )
        return resp

    def u2_set_fastinput_ime(self, enable: bool):
        self.u2.set_fastinput_ime(enable)

    def u2_current_ime(self):
        return self.u2.current_ime()

    def u2_send_keys(self, text: str, clear: bool=False):
        self.u2.send_keys(text=text, clear=clear)

    # 参考: https://uiautomator2.readthedocs.io/en/latest/api.html#uiautomator2.Session.send_action
    def u2_send_action(self, code):
        self.u2.send_action(code=code)

    def u2_clear_text(self):
        self.u2.clear_text()

    @property
    def clipboard(self):
        return self.u2.clipboard
    
    def set_clipboard(self, text, label=None):
        return self.u2.set_clipboard(text=text, label=label)
