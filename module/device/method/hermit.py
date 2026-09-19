"""Hermit 截图和控制后端。通过 HTTP 与 ADB 端口转发通信，
提供基于 JSON 协议的截图捕获和触摸注入功能。"""

import json
from functools import partial

import requests
from adbutils.errors import AdbError

from module.base.decorator import cached_property
from module.base.timer import Timer
from module.base.utils import point2str, random_rectangle_point
from module.device.method.retry import retry_backend, recover_adb, recover_unknown
from module.device.method.adb import Adb
from module.device.method.utils import HierarchyButton
from module.exception import RequestHumanTakeover
from module.logger import logger


class HermitError(Exception):
    pass


def _retry_recover(self, error, trial):
    def reconnect_hermit():
        self.adb_reconnect()
        self.hermit_init()

    if isinstance(error, (ConnectionResetError, AdbError)):
        return recover_adb(self, error)
    if isinstance(error, requests.exceptions.ConnectionError):
        logger.error(error)
        if 'Connection aborted' in str(error):
            return reconnect_hermit
        return self.adb_reconnect
    if isinstance(error, HermitError):
        logger.error(error)
        return reconnect_hermit
    return recover_unknown(error)


retry = partial(retry_backend, recover=_retry_recover, label='设备-Hermit')


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
        logger.hr('[设备-Hermit] Hermit初始化')

        self.app_stop_adb(self._hermit_package_name)
        # self.uninstall_hermit()

        logger.info('[设备-Hermit] 尝试启动Hermit')
        if self.app_start_adb(self._hermit_package_name, allow_failure=True):
            # 成功启动 hermit
            logger.info('[设备-Hermit] 启动Hermit成功')
        else:
            # Hermit 未安装
            logger.warning(f'[设备-Hermit] {self._hermit_package_name} 未找到，正在安装 hermit')
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
        logger.hr('启用无障碍服务')
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
                    logger.info(f'[设备-Hermit] 点击 {point2str(*point)} @ {b}')
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
                logger.critical('[设备-Hermit] 无法为 Hermit 打开辅助功能服务')
                logger.critical(
                    '\n\n'
                    '[设备-Hermit] 请手动执行以下操作：\n'
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
                logger.critical('[设备-Hermit] Hermit 无法在当前设备上运行，Hermit 需要 Android>=7.0')
                raise RequestHumanTakeover
            if 'accessibilityservice' in result:
                # 尝试调用虚拟方法
                # 'boolean android.accessibilityservice.AccessibilityService.dispatchGesture(
                #     android.accessibilityservice.GestureDescription,
                #     android.accessibilityservice.AccessibilityService$GestureResultCallback,
                #     android.os.Handler
                # )' on a null object reference
                logger.error('[设备-Hermit] 无法访问无障碍服务')
            raise e

        # Hermit 请求仅需 2-4ms
        # 添加 50ms 延迟因为游戏无法快速响应。
        self.sleep(0.05)
        return result

    @retry
    def click_hermit(self, x, y):
        self.hermit_send('/click', x=x, y=y)
