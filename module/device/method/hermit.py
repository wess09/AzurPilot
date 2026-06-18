import json
import time
from functools import wraps

import requests
from adbutils.errors import AdbError

from module.base.decorator import cached_property
from module.base.timer import Timer
from module.base.utils import point2str, random_rectangle_point
from module.device.method.adb import Adb
from module.device.method.utils import (RETRY_TRIES, handle_unknown_host_service, retry_sleep,
                                        HierarchyButton, handle_adb_error)
from module.exception import RequestHumanTakeover
from module.logger import logger


class HermitError(Exception):
    pass


def retry(func):
    @wraps(func)
    def retry_wrapper(self, *args, **kwargs):
        """
        Args:
            self (Hermit):
        """
        init = None
        for _ in range(RETRY_TRIES):
            try:
                if callable(init):
                    time.sleep(retry_sleep(_))
                    init()
                return func(self, *args, **kwargs)
            # 无法处理
            except RequestHumanTakeover:
                break
            # ADB 服务被终止时
            except ConnectionResetError as e:
                logger.error(e)

                def init():
                    self.adb_reconnect()
            # 无法发送请求时
            except requests.exceptions.ConnectionError as e:
                logger.error(e)
                text = str(e)
                if 'Connection aborted' in text:
                    # Hermit 未安装或未运行
                    # ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
                    def init():
                        self.adb_reconnect()
                        self.hermit_init()
                else:
                    # 连接丢失，ADB 服务被终止
                    # HTTPConnectionPool(host='127.0.0.1', port=20269):
                    # Max retries exceeded with url: /click?x=500&y=500
                    def init():
                        self.adb_reconnect()
            # ADB 错误
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
            # HermitError: {"code":-1,"msg":"error"}
            except HermitError as e:
                logger.error(e)

                def init():
                    self.adb_reconnect()
                    self.hermit_init()
            # 未知异常，可能是图像损坏
            except Exception as e:
                logger.exception(e)

                def init():
                    pass

        logger.critical(f'重试 {func.__name__}() 失败')
        raise RequestHumanTakeover

    return retry_wrapper


class Hermit(Adb):
    """
    Hermit 控制方案，https://github.com/LookCos/hermit。
    API 文档：https://www.lookcos.cn/docs/hermit#/zh-cn/API

    Hermit 有其他控制和截图 API，但效果都很差。
    Hermit 截图比 ADB 慢，且容易出现请求超时或图像损坏。
    每次操作都需要 root 权限，因此会一直显示 toast：Superuser granted to Hermit。

    Hermit 被加入 Alas 是为了在无法运行 uiautomator2 和 minitouch 的 vmos 上获得更好的性能。
    注意 Hermit 需要 Android>=7.0。
    """
    _hermit_port = 9999
    _hermit_package_name = 'com.lookcos.hermit'

    @property
    def _hermit_url(self):
        return f'http://127.0.0.1:{self._hermit_port}'

    def hermit_init(self):
        logger.hr('Hermit init')

        self.app_stop_adb(self._hermit_package_name)
        # self.uninstall_hermit()

        logger.info('Try to start hermit')
        if self.app_start_adb(self._hermit_package_name, allow_failure=True):
            # 成功启动 hermit
            logger.info('Success to start hermit')
        else:
            # Hermit 未安装
            logger.warning(f'{self._hermit_package_name} not found, installing hermit')
            self.adb_command(['install', '-t', self.config.HERMIT_FILEPATH_LOCAL])
            self.app_start_adb(self._hermit_package_name)

        # 启用辅助功能服务
        self.hermit_enable_accessibility()

        # 隐藏 Hermit
        # 0 -->  "KEYCODE_UNKNOWN"
        # 1 -->  "KEYCODE_MENU"
        # 2 -->  "KEYCODE_SOFT_RIGHT"
        # 3 -->  "KEYCODE_HOME"
        # 4 -->  "KEYCODE_BACK"
        # 5 -->  "KEYCODE_CALL"
        # 6 -->  "KEYCODE_ENDCALL"
        self.adb_shell(['input', 'keyevent', '3'])

        # 切换回碧蓝航线
        self.app_start_adb()

    def uninstall_hermit(self):
        self.adb_command(['uninstall', self._hermit_package_name])

    def hermit_enable_accessibility(self):
        """
        为 Hermit 开启辅助功能服务。

        Raises:
            RequestHumanTakeover: 失败时抛出，需要用户手动操作。
        """
        logger.hr('Enable accessibility service')
        interval = Timer(0.3)
        timeout = Timer(10, count=10).start()
        while 1:
            h = self.dump_hierarchy_adb()
            interval.wait()
            interval.reset()

            def appear(xpath):
                return bool(HierarchyButton(h, xpath))

            def appear_then_click(xpath):
                b = HierarchyButton(h, xpath)
                if b:
                    point = random_rectangle_point(b.button)
                    logger.info(f'Click {point2str(*point)} @ {b}')
                    self.click_adb(*point)
                    return True
                else:
                    return False

            if appear_then_click('//*[@text="Hermit" and @resource-id="android:id/title"]'):
                continue
            if appear_then_click('//*[@class="android.widget.Switch" and @checked="false"]'):
                continue
            if appear_then_click('//*[@resource-id="android:id/button1"]'):
                # 此处只做普通点击
                # 一旦 hermit 获得辅助功能权限，就不能再使用 uiautomator，
                # 否则 uiautomator 会接管权限。
                break
            if appear('//*[@class="android.widget.Switch" and @checked="true"]'):
                raise HermitError('Accessibility service already enable but get error')

            # 超时
            if timeout.reached():
                logger.critical('无法为 Hermit 打开辅助功能服务')
                logger.critical(
                    '\n\n'
                    '请手动执行以下操作：\n'
                    '1. 在辅助功能设置中找到 "Hermit" 并点击\n'
                    '2. 将其打开并点击 "确定"\n'
                    '3. 切换回碧蓝航线\n'
                )
                raise RequestHumanTakeover

    @cached_property
    def hermit_session(self):
        session = requests.Session()
        session.trust_env = False  # 忽略代理
        self._hermit_port = self.adb_forward('tcp:9999')
        return session

    def hermit_send(self, url, **kwargs):
        """
        发送 HTTP 请求到 Hermit 服务。

        Args:
            url: 请求路径。
            **kwargs: 请求参数。

        Returns:
            响应字典，通常为 {"code":0,"msg":"ok"}。
        """
        result = self.hermit_session.get(f'{self._hermit_url}{url}', params=kwargs, timeout=3).text
        try:
            result = json.loads(result, encoding='utf-8')
            if result['code'] != 0:
                # {"code":-1,"msg":"error"}
                raise HermitError(result)
        except (json.decoder.JSONDecodeError, KeyError):
            e = HermitError(result)
            if 'GestureDescription$Builder' in result:
                logger.error(e)
                logger.critical('Hermit 无法在当前设备上运行，Hermit 需要 Android>=7.0')
                raise RequestHumanTakeover
            if 'accessibilityservice' in result:
                # 尝试调用虚拟方法
                # 'boolean android.accessibilityservice.AccessibilityService.dispatchGesture(
                #     android.accessibilityservice.GestureDescription,
                #     android.accessibilityservice.AccessibilityService$GestureResultCallback,
                #     android.os.Handler
                # )' on a null object reference
                logger.error('Unable to access accessibility service')
            raise e

        # Hermit 请求仅需 2-4ms
        # 添加 50ms 延迟因为游戏无法快速响应。
        self.sleep(0.05)
        return result

    @retry
    def click_hermit(self, x, y):
        self.hermit_send('/click', x=x, y=y)
