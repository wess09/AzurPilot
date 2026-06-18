import logging
import os

from deploy.Windows.emulator import EmulatorManager
from deploy.Windows.logger import Progress, logger


def show_fix_tip(module):
    logger.info(f"""
    To fix this:
    1. Re-run the launcher so uv can refresh the local .venv
    2. If the problem persists, run:
        ./.venv/Scripts/uv.exe sync --frozen --no-dev --no-install-project --reinstall-package {module}
    3. Re-open AzurPilot.exe
    """)


class AdbManager(EmulatorManager):
    def adb_install(self):
        logger.hr('Start ADB service', 0)

        if self.ReplaceAdb:
            logger.hr('Replace ADB', 1)
            self.adb_replace()
            Progress.AdbReplace()
        if self.AutoConnect:
            logger.hr('ADB Connect', 1)
            self.brute_force_connect()
            Progress.AdbConnect()

        if False:
            logger.hr('Uiautomator2 Init', 1)
            try:
                import adbutils
                from uiautomator2 import init
            except ModuleNotFoundError as e:
                message = str(e)
                for module in ['apkutils2', 'progress']:
                    # 常见的模块缺失错误
                    if module in message:
                        show_fix_tip(module)
                        exit(1)
                raise

            # 移除全局代理设置，否则 uiautomator2 会走代理
            for k in list(os.environ.keys()):
                if k.lower().endswith('_proxy'):
                    del os.environ[k]

            for device in adbutils.adb.iter_device():
                initer = init.Initer(device, loglevel=logging.DEBUG)
                # MuMu X 没有 ro.product.cpu.abi，从 ro.product.cpu.abilist 中取第一个
                if initer.abi not in ['x86_64', 'x86', 'arm64-v8a', 'armeabi-v7a', 'armeabi']:
                    initer.abi = initer.abis[0]
                initer.set_atx_agent_addr('127.0.0.1:7912')

                for _ in range(2):
                    try:
                        initer.install()
                        break
                    except AssertionError:
                        logger.info(f'AssertionError when installing uiautomator2 on device {device.serial}')
                        logger.info('If you are using BlueStacks or LD player or WSA, '
                                    'please enable ADB in the settings of your emulator')
                        exit(1)
                    except ConnectionError:
                        if _ == 1:
                            raise
                        init.GITHUB_BASEURL = 'http://tool.appetizer.io/openatx'

                initer._device.shell(["rm", "/data/local/tmp/minicap"])
                initer._device.shell(["rm", "/data/local/tmp/minicap.so"])
