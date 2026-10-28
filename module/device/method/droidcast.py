"""
DroidCast 截图方法。

通过 DroidCast 投屏服务执行设备截图，适用于 ADB screencap 不可用的场景。
DroidCast 是一个运行在 Android 设备上的截图服务，通过 HTTP 接口提供屏幕图像。
支持 DroidCast 和 DroidCast_raw 两种模式：前者返回 PNG/JPEG 图像，
后者直接返回原始像素数据以获得更高性能。需要先在设备上安装并启动 DroidCast APK。
"""
import typing as t
from functools import partial

import cv2
import numpy as np
import requests
from adbutils.errors import AdbError

from module.base.decorator import cached_property, del_cached_property
from module.base.timer import Timer
from module.device.method.retry import retry_backend, recover_adb, recover_truncated_image, recover_unknown
from module.device.method.uiautomator_2 import ProcessInfo, Uiautomator2
from module.device.method.utils import ImageTruncated, PackageNotInstalled
from module.exception import EmulatorNotRunningError
from module.logger import logger


class DroidCastVersionIncompatible(Exception):
    """DroidCast 版本与请求模式不兼容。"""
    pass


def _retry_recover(self, error, trial):
    """DroidCast 操作失败后的异常恢复策略。

    Args:
        self: 设备实例。
        error: 捕获的异常对象。
        trial: 当前重试轮次。

    Returns:
        可调用的恢复函数，若无法恢复则返回 None。
    """
    if isinstance(error, (ConnectionResetError, AdbError)):
        return recover_adb(self, error)
    if isinstance(error, PackageNotInstalled):
        logger.error(error)
        return self.detect_package
    if isinstance(error, (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout,
                          DroidCastVersionIncompatible)):
        logger.error(error)
        return self.droidcast_init
    if isinstance(error, ImageTruncated):
        return recover_truncated_image(self, error)
    return recover_unknown(error)


retry = partial(retry_backend, recover=_retry_recover, label='设备-DroidCast')


class DroidCast(Uiautomator2):
    """DroidCast 截图方案与 DroidCast_raw 高性能位图传输方案。"""

    _droidcast_port: int = 0
    droidcast_width: int = 0
    droidcast_height: int = 0
    _droidcast_raw_transposed: bool = False
    _droidcast_raw_probe_key: t.Optional[tuple] = None

    @cached_property
    def droidcast_session(self):
        """获取或创建与 DroidCast 服务通信的 HTTP Session。

        Returns:
            requests.Session: 已配置端口映射和直连环境的 Session 对象。
        """
        session = requests.Session()
        session.trust_env = False  # 忽略代理
        self._droidcast_port = self.adb_forward('tcp:53516')
        return session

    """
    可用 API 参考源码：
    https://github.com/Torther/DroidCast_raw/blob/DroidCast_raw/app/src/main/java/ink/mol/droidcast_raw/KtMain.kt
    可用接口：
    - /screenshot
        获取 RGB565 位图
    - /preview
        获取 PNG 截图
    """

    def _droidcast_raw_probe_transposed(self, shape):
        """探测 DroidCast_raw 服务端输出的像素排布是否为转置的竖排数据。

        部分设备（例如反向横屏 orientation=2 的 redroid）上，DroidCast_raw 直接读取
        帧缓冲，返回的是竖排数据。它与横屏的 (height, width) 形状字节数完全相同，
        reshape 后画面整体错位，模板匹配全部失效。这里读取 `/preview` 的 PNG 头，
        取得服务端实际输出尺寸。`/preview` 需要服务端完整编码一次 PNG，耗时在
        400 ms 以上，因此结果按 (方向, 形状) 缓存，只在方向或分辨率变化、以及
        DroidCast 服务重新初始化之后探测一次。探测失败时沿用上一次的结论，
        避免每帧都付出探测成本。

        Args:
            shape (tuple): 期望的横图形状 (height, width)。

        Returns:
            bool: 服务端输出竖排数据时返回 True。
        """
        key = (self.orientation, shape)
        if self._droidcast_raw_probe_key == key:
            return self._droidcast_raw_transposed

        transposed = self._droidcast_raw_transposed
        try:
            resp = self.droidcast_session.get(self.droidcast_url('/preview'), timeout=3, stream=True)
            try:
                head = resp.raw.read(33)
            finally:
                resp.close()
            # PNG：8 字节签名，4 字节块长度，4 字节块类型，随后 IHDR 的宽与高各占 4 字节大端
            if len(head) >= 24 and head[:8] == b'\x89PNG\r\n\x1a\n' and head[12:16] == b'IHDR':
                width = int.from_bytes(head[16:20], 'big')
                height = int.from_bytes(head[20:24], 'big')
                if width and height:
                    logger.attr('截图原始尺寸', f'{width}x{height}')
                    transposed = (width, height) == (shape[0], shape[1])
                    # 只在成功解析时写缓存，读取失败时下一帧继续尝试，
                    # 避免一次临时故障让错误的排布判断一直沿用下去
                    self._droidcast_raw_probe_key = key
        except Exception as e:
            logger.warning(f'[设备-DroidCast] 探测原始尺寸失败: {e}')

        self._droidcast_raw_transposed = transposed
        if transposed:
            logger.attr('截图方向', '服务端输出竖排数据，已转回横图')
        return transposed

    def _droidcast_raw_reshape(self, arr, shape):
        """将 DroidCast_raw 的一维 RGB565 数据还原为横图。

        Args:
            arr (np.ndarray): 一维 RGB565 像素数组。
            shape (tuple): 期望的横图形状 (height, width)。

        Returns:
            np.ndarray: (height, width) 的像素数组。
        """
        if arr.size != shape[0] * shape[1] or not self._droidcast_raw_probe_transposed(shape):
            return arr.reshape(shape)

        # 服务端按竖排输出，先还原成 (width, height)，再按设备方向旋转回横图
        image = arr.reshape(shape[1], shape[0])
        if self.orientation == 1:
            return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)

    def droidcast_url(self, url='/preview'):
        """获取标准 DroidCast 服务的请求 URL。

        Args:
            url (str): 接口路由路径，默认为 '/preview'。

        Returns:
            str: 包含端口与尺寸参数的完整 HTTP 请求地址。
        """
        if self.is_mumu_over_version_356:
            w, h = self.droidcast_width, self.droidcast_height
            if self.orientation == 0:
                return f'http://127.0.0.1:{self._droidcast_port}{url}?width={w}&height={h}'
            elif self.orientation == 1:
                return f'http://127.0.0.1:{self._droidcast_port}{url}?width={h}&height={w}'
            else:
                # logger.warning('DroidCast receives invalid device orientation')
                pass

        return f'http://127.0.0.1:{self._droidcast_port}{url}'

    def droidcast_raw_url(self, url='/screenshot'):
        """获取 DroidCast_raw 服务的请求 URL。

        Args:
            url (str): 接口路由路径，默认为 '/screenshot'。

        Returns:
            str: 包含端口与尺寸参数的完整 HTTP 请求地址。
        """
        if self.is_mumu_over_version_356:
            w, h = self.droidcast_width, self.droidcast_height
            if self.orientation == 0:
                return f'http://127.0.0.1:{self._droidcast_port}{url}?width={w}&height={h}'
            elif self.orientation == 1:
                return f'http://127.0.0.1:{self._droidcast_port}{url}?width={h}&height={w}'
            else:
                # logger.warning('DroidCast receives invalid device orientation')
                pass

        return f'http://127.0.0.1:{self._droidcast_port}{url}'

    def droidcast_init(self):
        """初始化并启动设备上的 DroidCast 服务。"""
        logger.hr('[设备-DroidCast] DroidCast初始化')
        self._droidcast_raw_probe_key = None
        self.droidcast_stop()
        self._droidcast_update_resolution()

        logger.info('[设备-DroidCast] 推送DroidCast APK')
        self.adb_push(self.config.DROIDCAST_FILEPATH_LOCAL, self.config.DROIDCAST_FILEPATH_REMOTE)

        logger.info('[设备-DroidCast] 启动DroidCast APK')
        # DroidCast_raw-release-1.1.apk
        # CLASSPATH=/data/local/tmp/DroidCast_raw.apk app_process / ink.mol.droidcast_raw.Main > /dev/null
        # adb shell CLASSPATH=/data/local/tmp/DroidCast_raw.apk app_process / ink.mol.droidcast_raw.Main
        resp = self.u2_shell_background([
            'CLASSPATH=/data/local/tmp/DroidCast_raw.apk',
            'app_process',
            '/',
            'ink.mol.droidcast_raw.Main',
            '>',
            '/dev/null'
        ])
        logger.info(resp)
        del_cached_property(self, 'droidcast_session')
        _ = self.droidcast_session

        if self.config.DROIDCAST_VERSION == 'DroidCast':
            logger.attr('DroidCast地址', self.droidcast_url())
            self.droidcast_wait_startup()
        elif self.config.DROIDCAST_VERSION == 'DroidCast_raw':
            logger.attr('DroidCast原始地址', self.droidcast_raw_url())
            self.droidcast_wait_startup()
        else:
            logger.error(f'未知的DROIDCAST版本: {self.config.DROIDCAST_VERSION}')

    def _droidcast_update_resolution(self):
        """更新设备屏幕分辨率缓存，用于特定模拟器版本的尺寸校准。"""
        if self.is_mumu_over_version_356:
            logger.info('[设备-DroidCast] 更新DroidCast分辨率')
            w, h = self.resolution_uiautomator2(cal_rotation=False)
            self.get_orientation()
            # 720, 1280
            # mumu12 > 3.5.6 始终为竖屏设备
            self.droidcast_width, self.droidcast_height = w, h
            logger.info(f'DroidCast分辨率: {(w, h)}')

    @retry(on_exhausted=EmulatorNotRunningError)
    def screenshot_droidcast(self):
        """通过 DroidCast 接口截取屏幕图像（PNG/JPEG 模式）。

        Returns:
            np.ndarray: RGB 格式的屏幕截图。

        Raises:
            DroidCastVersionIncompatible: 服务端未提供对应接口或版本不匹配。
            ImageTruncated: 图像数据截断或解析失败。
        """
        self.config.DROIDCAST_VERSION = 'DroidCast'
        if self.is_mumu_over_version_356:
            if not self.droidcast_width or not self.droidcast_height:
                self._droidcast_update_resolution()

        resp = self.droidcast_session.get(self.droidcast_url(), timeout=3)

        if resp.status_code == 404:
            raise DroidCastVersionIncompatible('DroidCast server does not have /preview')
        image = resp.content
        image = np.frombuffer(image, np.uint8)
        if image is None:
            raise ImageTruncated('Empty image after reading from buffer')
        if image.shape == (1843200,):
            raise DroidCastVersionIncompatible('Requesting screenshots from `DroidCast` but server is `DroidCast_raw`')
        if image.size < 500:
            logger.warning(f'[设备-DroidCast] 异常截图: {resp.content}')

        image = cv2.imdecode(image, cv2.IMREAD_COLOR)
        if image is None:
            raise ImageTruncated('Empty image after cv2.imdecode')

        cv2.cvtColor(image, cv2.COLOR_BGR2RGB, dst=image)
        if image is None:
            raise ImageTruncated('Empty image after cv2.cvtColor')

        if self.is_mumu_over_version_356:
            if self.orientation == 1:
                image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)

        return image

    @retry(on_exhausted=EmulatorNotRunningError)
    def screenshot_droidcast_raw(self):
        """通过 DroidCast_raw 接口截取原始像素并转换为 RGB 图像。

        Returns:
            np.ndarray: RGB 格式的屏幕截图。

        Raises:
            ConnectionError: 服务端返回错误信息或连接中断。
            DroidCastVersionIncompatible: 服务端版本与 raw 模式不匹配。
            ImageTruncated: 原始位图数据损坏或尺寸不匹配。
        """
        self.config.DROIDCAST_VERSION = 'DroidCast_raw'
        shape = (720, 1280)
        if self.is_mumu_over_version_356:
            if not self.droidcast_width or not self.droidcast_height:
                self._droidcast_update_resolution()
            if self.droidcast_height and self.droidcast_width:
                shape = (self.droidcast_height, self.droidcast_width)

        rotate = self.is_mumu_over_version_356 and self.orientation == 1

        resp = self.droidcast_session.get(self.droidcast_raw_url(), timeout=3)
        image = resp.content
        # DroidCast_raw 返回 RGB565 位图

        # 防止空内容导致 np.frombuffer 抛出 TypeError
        if image is None or len(image) == 0:
            raise ImageTruncated('Empty image content from DroidCast_raw')

        # DroidCast 返回了短错误信息而非原始位图数据
        # 例如 b':(  Failed to generate the screenshot on device / emulator: ...'
        # 抛出 ConnectionError 以在重试处理器中立即触发 droidcast_init
        if len(image) < 500:
            logger.warning(f'[设备-DroidCast] 异常截图: {image}')
            raise requests.exceptions.ConnectionError(f'DroidCast service error: {image!r}')

        try:
            arr = np.frombuffer(image, dtype=np.uint16)
            if rotate:
                arr = arr.reshape(shape)
                # arr = cv2.rotate(arr, cv2.ROTATE_90_CLOCKWISE)
                # 稍微快一点？
                arr = cv2.transpose(arr)
                cv2.flip(arr, 1, dst=arr)
            else:
                arr = self._droidcast_raw_reshape(arr, shape)
        except ValueError as e:
            # 尝试作为 `DroidCast` 格式加载
            image = np.frombuffer(image, np.uint8)
            if image is not None:
                image = cv2.imdecode(image, cv2.IMREAD_COLOR)
                if image is not None:
                    raise DroidCastVersionIncompatible(
                        'Requesting screenshots from `DroidCast_raw` but server is `DroidCast`')
            # ValueError: cannot reshape array of size 0 into shape (720,1280)
            raise ImageTruncated(f'{e}\n如果模拟器分辨率不是 1280x720，请将模拟器分辨率设置为 1280x720')

        # 将 RGB565 转换为 RGB888
        # https://blog.csdn.net/happy08god/article/details/10516871

        # r = (arr & 0b1111100000000000) >> (11 - 3)
        # g = (arr & 0b0000011111100000) >> (5 - 2)
        # b = (arr & 0b0000000000011111) << 3
        # r |= (r & 0b11000000) >> 5
        # g |= (g & 0b11000000) >> 6
        # b |= (b & 0b11100000) >> 5
        # r = r.astype(np.uint8)
        # g = g.astype(np.uint8)
        # b = b.astype(np.uint8)
        # image = cv2.merge([r, g, b])

        # 与上方代码功能相同，但耗时约 2.7ms 而非 16ms。
        # 注意 cv2.convertScaleAbs 比 cv2.multiply 快 5 倍，cv2.add 比 cv2.convertScaleAbs 快 8 倍
        # 注意 cv2.convertScaleAbs 包含四舍五入
        tmp = np.empty_like(arr)
        cv2.bitwise_and(arr, 0b1111100000000000, dst=tmp)
        r = cv2.convertScaleAbs(tmp, alpha=0.0040283203125)  # 0.00390625 * 1.03125
        cv2.bitwise_and(arr, 0b0000011111100000, dst=tmp)
        g = cv2.convertScaleAbs(tmp, alpha=0.126953125)  # 0.125 * 1.015625
        cv2.bitwise_and(arr, 0b0000000000011111, dst=tmp)
        b = cv2.convertScaleAbs(tmp, alpha=8.25)  # 8 * 1.03125

        image = cv2.merge([r, g, b])

        return image

    def droidcast_wait_startup(self):
        """等待 DroidCast 启动完成。

        Returns:
            bool: 启动成功返回 True，超时返回 False。
        """
        timeout = Timer(10).start()
        while 1:
            self.sleep(0.25)
            if timeout.reached():
                break

            try:
                resp = self.droidcast_session.get(self.droidcast_url('/'), timeout=3)
                # 路由 `/` 不可用，但 404 表示启动已完成
                if resp.status_code == 404:
                    logger.attr('DroidCast状态', '在线')
                    return True
            except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
                logger.attr('DroidCast状态', '离线')

        logger.warning('[设备-DroidCast] DroidCast启动超时，假定已启动')
        return False

    def droidcast_uninstall(self):
        """停止 DroidCast 进程并删除 DroidCast APK。

        DroidCast 并非真正安装，而是通过 JAVA 类调用，卸载即删除文件。
        """
        self.droidcast_stop()
        logger.info('[设备-DroidCast] 移除DroidCast')
        self.adb_shell(["rm", self.config.DROIDCAST_FILEPATH_REMOTE])

    def _iter_droidcast_proc(self) -> t.Iterable[ProcessInfo]:
        """迭代查找运行中的 DroidCast 进程。

        Yields:
            ProcessInfo: 匹配到的进程信息对象。
        """
        processes = self.proc_list_uiautomator2()
        for proc in processes:
            if 'com.rayworks.droidcast.Main' in proc.cmdline:
                yield proc
            if 'com.torther.droidcasts.Main' in proc.cmdline:
                yield proc
            if 'ink.mol.droidcast_raw.Main' in proc.cmdline:
                yield proc

    def droidcast_stop(self):
        """停止 DroidCast 进程。"""
        logger.info('[设备-DroidCast] 停止DroidCast')
        for proc in self._iter_droidcast_proc():
            logger.info(f'[设备-DroidCast] 终止进程PID={proc.pid}')
            self.adb_shell(['kill', '-s', 9, proc.pid])
