import os
import time
from collections import deque
from datetime import datetime
from PIL import Image
# 此文件定义了截图处理逻辑。
# 管理各种截图捕获方式，并包含后台编码线程用于将图像序列化并通过 Base64 供 WebUI 实时渲染预览。
import base64
import threading
import queue as _queue

import cv2
import numpy as np

from module.base.decorator import cached_property
from module.base.timer import Timer
from module.base.utils import get_color, image_size, limit_in, save_image, set_template_match_non_native_720p
from module.device.method.adb import Adb
from module.device.method.ascreencap import AScreenCap
from module.device.method.droidcast import DroidCast
from module.device.method.ldopengl import LDOpenGL
from module.device.method.nemu_ipc import NemuIpc
from module.device.method.scrcpy import Scrcpy
from module.device.method.wsa import WSA
from module.exception import RequestHumanTakeover, ScriptError
from module.logger import logger

class Screenshot(Adb, WSA, DroidCast, AScreenCap, Scrcpy, NemuIpc, LDOpenGL):
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    _screen_size_checked = False
    _screen_black_checked = False
    _minicap_uninstalled = False
    _screenshot_interval = Timer(0.1)
    _last_save_time = {}
    image: np.ndarray

    @cached_property
    def screenshot_methods(self):
        return {
            'ADB': self.screenshot_adb,
            'ADB_nc': self.screenshot_adb_nc,
            'uiautomator2': self.screenshot_uiautomator2,
            'aScreenCap': self.screenshot_ascreencap,
            'aScreenCap_nc': self.screenshot_ascreencap_nc,
            'DroidCast': self.screenshot_droidcast,
            'DroidCast_raw': self.screenshot_droidcast_raw,
            'scrcpy': self.screenshot_scrcpy,
            'nemu_ipc': self.screenshot_nemu_ipc,
            'ldopengl': self.screenshot_ldopengl,
        }

    @cached_property
    def screenshot_method_override(self) -> str:
        return ''

    def screenshot(self):
        """截取屏幕截图。

        Returns:
            np.ndarray: 截取的屏幕图像。
        """
        self._screenshot_interval.wait()
        self._screenshot_interval.reset()

        for _ in range(2):
            if self.screenshot_method_override:
                method = self.screenshot_method_override
            else:
                method = self.config.Emulator_ScreenshotMethod
            method = self.screenshot_methods.get(method, self.screenshot_adb)

            self.image = method()

            width, height = image_size(self.image)
            set_template_match_non_native_720p(width != 1280 or height != 720, resolution=(width, height))
            if width != 1280 or height != 720:
                self.image = self.resize_screenshot_to_720p(self.image)

            if self.config.Emulator_ScreenshotDedithering:
                # 此操作大约需要 40-60ms
                cv2.fastNlMeansDenoising(self.image, self.image, h=17, templateWindowSize=1, searchWindowSize=2)
            self.image = self._handle_orientated_image(self.image)

            if self.config.Error_SaveError:
                self.screenshot_deque.append({'time': datetime.now(), 'image': self.image})

            if self.check_screen_size() and self.check_screen_black():
                break
            else:
                continue

        return self.image

    @staticmethod
    def resize_screenshot_to_720p(image):
        """将截图归一化到 Alas 的 1280x720 资源空间。

        已在 MuMu 模拟器的 1600x900、1920x1080、2560x1440 和 3840x2160 分辨率下测试。
        使用三次下采样并配合轻度高斯模糊混合，最接近原生 720p 效果。
        """
        image = cv2.resize(image, (1280, 720), interpolation=cv2.INTER_CUBIC)
        blur = cv2.GaussianBlur(image, (0, 0), sigmaX=1.0, sigmaY=1.0)
        return cv2.addWeighted(image, 0.90, blur, 0.10, 0)

    @property
    def has_cached_image(self):
        return hasattr(self, 'image') and self.image is not None

    def _handle_orientated_image(self, image):
        """处理旋转的截图图像。

        Args:
            image: 待处理的图像。

        Returns:
            处理后的图像。
        """
        width, height = image_size(self.image)
        if width == 1280 and height == 720:
            return image

        # 仅在非 1280x720 时旋转截图
        if self.orientation == 0:
            pass
        elif self.orientation == 1:
            image = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
        elif self.orientation == 2:
            image = cv2.rotate(image, cv2.ROTATE_180)
        elif self.orientation == 3:
            image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        else:
            raise ScriptError(f'Invalid device orientation: {self.orientation}')

        return image

    @cached_property
    def screenshot_deque(self):
        try:
            length = int(self.config.Error_ScreenshotLength)
        except ValueError:
            logger.error(f'Error_ScreenshotLength={self.config.Error_ScreenshotLength} is not an integer')
            raise RequestHumanTakeover
        # 限制在 1~400 范围内
        length = max(1, min(length, 400))
        return deque(maxlen=length)

    def save_screenshot(self, genre='items', interval=None, to_base_folder=False):
        """保存截图。使用毫秒时间戳作为文件名。

        Args:
            genre: 截图类型。
            interval: 两次保存之间的最小间隔（秒）。间隔内的保存将被跳过。
            to_base_folder: 是否保存到基础文件夹。

        Returns:
            保存成功返回 True。
        """
        now = time.time()
        if interval is None:
            interval = self.config.SCREEN_SHOT_SAVE_INTERVAL

        if now - self._last_save_time.get(genre, 0) > interval:
            fmt = 'png'
            file = '%s.%s' % (int(now * 1000), fmt)

            folder = self.config.SCREEN_SHOT_SAVE_FOLDER_BASE if to_base_folder else self.config.SCREEN_SHOT_SAVE_FOLDER
            folder = os.path.join(folder, genre)
            if not os.path.exists(folder):
                os.mkdir(folder)

            file = os.path.join(folder, file)
            self.image_save(file)
            self._last_save_time[genre] = now
            return True
        else:
            self._last_save_time[genre] = now
            return False

    def screenshot_last_save_time_reset(self, genre):
        self._last_save_time[genre] = 0

    def screenshot_interval_set(self, interval=None):
        """设置截图间隔。

        Args:
            interval: 两次截图之间的最小间隔（秒）。
                None 表示使用 Optimization_ScreenshotInterval，
                'combat' 表示使用 Optimization_CombatScreenshotInterval。
        """
        if interval is None:
            origin = self.config.Optimization_ScreenshotInterval
            interval = limit_in(origin, 0.001, 0.3)
            if interval != origin:
                logger.warning(f'Optimization.ScreenshotInterval {origin} is revised to {interval}')
                self.config.Optimization_ScreenshotInterval = interval
            # 允许 nemu_ipc 使用更低的默认值
            if self.config.Emulator_ScreenshotMethod in ['nemu_ipc', 'ldopengl']:
                interval = limit_in(origin, 0.001, 0.2)
        elif interval == 'combat':
            origin = self.config.Optimization_CombatScreenshotInterval
            interval = limit_in(origin, 0.001, 1.0)
            if interval != origin:
                logger.warning(f'Optimization.CombatScreenshotInterval {origin} is revised to {interval}')
                self.config.Optimization_CombatScreenshotInterval = interval
        elif isinstance(interval, (int, float)):
            # 代码中手动设置无限制
            pass
        else:
            logger.warning(f'Unknown screenshot interval: {interval}')
            raise ScriptError(f'Unknown screenshot interval: {interval}')
        # scrcpy 的截图间隔无意义，视频流会持续接收，无论是否使用。
        if self.config.Emulator_ScreenshotMethod == 'scrcpy':
            interval = 0.1

        if interval != self._screenshot_interval.limit:
            logger.info(f'Screenshot interval set to {interval}s')
            self._screenshot_interval.limit = interval

    def image_show(self, image=None):
        if image is None:
            image = self.image
        Image.fromarray(image).show()

    def image_save(self, file=None):
        if file is None:
            file = f'{int(time.time() * 1000)}.png'
        save_image(self.image, file)

    def check_screen_size(self):
        """检查屏幕分辨率是否为 1280x720。

        调用前需先截取截图。
        """
        if self._screen_size_checked:
            return True

        orientated = False
        for _ in range(2):
            # 检查屏幕分辨率
            width, height = image_size(self.image)
            logger.attr('Screen_size', f'{width}x{height}')
            if width == 1280 and height == 720:
                self._screen_size_checked = True
                return True
            elif not orientated and (width == 720 and height == 1280):
                logger.info('Received orientated screenshot, handling')
                self.get_orientation()
                self.image = self._handle_orientated_image(self.image)
                orientated = True
                width, height = image_size(self.image)
                if width == 720 and height == 1280:
                    logger.info('Unable to handle orientated screenshot, continue for now')
                    return True
                else:
                    continue
            elif self.config.Emulator_Serial == 'wsa-0':
                self.display_resize_wsa(0)
                return False
            elif hasattr(self, 'app_is_running') and not self.app_is_running():
                logger.warning('Received orientated screenshot, game not running')
                return True
            else:
                logger.critical(f"大叔，你看着分辨率对吗: {width}x{height}。真是个连分辨率都不会设的杂鱼呢❤")
                logger.critical("乖乖给我改成 1280x720 哦，不然我可不理你了❤")
                raise RequestHumanTakeover

    def check_screen_black(self):
        if self._screen_black_checked:
            return True
        # 检查屏幕颜色，某些模拟器可能会获取纯黑截图。
        color = get_color(self.image, area=(0, 0, 1280, 720))
        if sum(color) < 1:
            if self.config.Emulator_Serial == 'wsa-0':
                for _ in range(2):
                    display = self.get_display_id()
                    if display == 0:
                        return True
                logger.info(f'Game running on display {display}')
                logger.warning('Game not running on display 0, will be restarted')
                self.app_stop_uiautomator2()
                return False
            elif self.config.Emulator_ScreenshotMethod == 'uiautomator2':
                logger.warning(f'Received pure black screenshots from emulator, color: {color}')
                logger.warning('Uninstall minicap and retry')
                logger.warning('截图为纯黑色。通常是设备处于锁屏状态，或者当前模拟器不支持当前截图方式。')
                self.uninstall_minicap()
                self._screen_black_checked = False
                return False
            else:
                logger.warning(f'Received pure black screenshots from emulator, color: {color}')
                logger.warning(f'Screenshot method `{self.config.Emulator_ScreenshotMethod}` '
                               f'may not work on emulator `{self.serial}`, or the emulator is not fully started')
                if self.is_mumu_family:
                    if self.config.Emulator_ScreenshotMethod == 'DroidCast':
                        self.droidcast_stop()
                    else:
                        logger.warning('If you are using MuMu X, please upgrade to version >= 12.1.5.0')
                self._screen_black_checked = False
                return False
        else:
            self._screen_black_checked = True
            return True
