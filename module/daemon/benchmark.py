import time
import typing as t

import numpy as np
from rich.table import Table
from rich.text import Text

from module.base.utils import float2str as float2str_
from module.base.utils import random_rectangle_point
from module.campaign.campaign_ui import CampaignUI
from module.daemon.daemon_base import DaemonBase
from module.exception import RequestHumanTakeover
from module.logger import logger


def float2str(n, decimal=3):
    """将数值转换为带 's' 后缀的时间字符串。

    Args:
        n: 待转换的数值，非数值类型直接转字符串。
        decimal: 小数位数，默认保留 3 位。

    Returns:
        str: 格式化后的时间字符串，如 '0.319s'。
    """
    if not isinstance(n, (float, int)):
        return str(n)
    else:
        return float2str_(n, decimal=decimal) + 's'


class Benchmark(DaemonBase, CampaignUI):
    TEST_TOTAL = 15
    TEST_BEST = int(TEST_TOTAL * 0.8)

    def benchmark_test(self, func, *args, **kwargs):
        """对指定函数执行多次基准测试，返回平均耗时。

        连续调用 func TEST_TOTAL 次，去掉最慢的 20% 结果后取平均值。
        若中途出现 RequestHumanTakeover 或其他异常则立即返回 'Failed'。

        Args:
            func: 待测试的函数。
            *args: 传递给 func 的位置参数。
            **kwargs: 传递给 func 的关键字参数。

        Returns:
            float: 去除异常值后的平均耗时（秒），失败时返回 'Failed'。

        Raises:
            RequestHumanTakeover: 不捕获此异常，直接向上抛出。
        """
        logger.hr(f'Benchmark test', level=2)
        logger.info(f'Testing function: {func.__name__}')
        record = []

        for n in range(1, self.TEST_TOTAL + 1):
            start = time.perf_counter()

            try:
                func(*args, **kwargs)
            except RequestHumanTakeover:
                logger.critical('错误 请求人类接管')
                logger.warning(f'基准测试失败，函数: {func.__name__}')
                return 'Failed'
            except Exception as e:
                logger.exception(e)
                logger.warning(f'基准测试失败，函数: {func.__name__}')
                return 'Failed'

            cost = time.perf_counter() - start
            logger.attr(
                f'{str(n).rjust(2, "0")}/{self.TEST_TOTAL}',
                f'{float2str(cost)}'
            )
            record.append(cost)

        logger.info('Benchmark tests done')
        average = float(np.mean(np.sort(record)[:self.TEST_BEST]))
        logger.info(f'Time cost {float2str(average)} ({self.TEST_BEST} best results out of {self.TEST_TOTAL} tests)')
        return average

    @staticmethod
    def evaluate_screenshot(cost):
        """根据截图耗时评估速度等级，返回带颜色样式的 Rich Text。

        Args:
            cost: 截图耗时（秒），非数值时表示失败。

        Returns:
            Text: 带颜色标签的速度描述文本。
        """
        if not isinstance(cost, (float, int)):
            return Text(cost, style="bold bright_red")

        if cost < 0.025:
            return Text('Insane Fast', style="bold bright_green")
        if cost < 0.100:
            return Text('Ultra Fast', style="bold bright_green")
        if cost < 0.200:
            return Text('Very Fast', style="bright_green")
        if cost < 0.300:
            return Text('Fast', style="green")
        if cost < 0.500:
            return Text('Medium', style="yellow")
        if cost < 0.750:
            return Text('Slow', style="red")
        if cost < 1.000:
            return Text('Very Slow', style="bright_red")
        return Text('Ultra Slow', style="bold bright_red")

    @staticmethod
    def evaluate_click(cost):
        """根据点击耗时评估速度等级，返回带颜色样式的 Rich Text。

        Args:
            cost: 点击耗时（秒），非数值时表示失败。

        Returns:
            Text: 带颜色标签的速度描述文本。
        """
        if not isinstance(cost, (float, int)):
            return Text(cost, style="bold bright_red")

        if cost < 0.100:
            return Text('Fast', style="bright_green")
        if cost < 0.200:
            return Text('Medium', style="yellow")
        if cost < 0.400:
            return Text('Slow', style="red")
        return Text('Very Slow', style="bright_red")

    @staticmethod
    def show(test, data, evaluate_func):
        """以表格形式展示基准测试结果。

        输出示例:
            +--------------+--------+--------+
            |  Screenshot  |  time  | Speed  |
            +--------------+--------+--------+
            |     ADB      | 0.319s |  Fast  |
            | uiautomator2 | 0.476s | Medium |
            |  aScreenCap  | Failed | Failed |
            +--------------+--------+--------+

        Args:
            test: 表格第一列的标题名称。
            data: 测试结果列表，每项为 [方法名, 耗时]。
            evaluate_func: 耗时评估函数，返回带颜色的 Rich Text。
        """
        table = Table(show_lines=True)
        table.add_column(
            test, header_style="bright_cyan", style="cyan", no_wrap=True
        )
        table.add_column("Time", style="magenta")
        table.add_column("Speed", style="green")
        for row in data:
            table.add_row(
                row[0],
                float2str(row[1]),
                evaluate_func(row[1]),
            )
        logger.print(table, justify='center')

    def benchmark(self, screenshot: t.Tuple[str] = (), click: t.Tuple[str] = ()):
        """执行截图和点击方法的基准测试，返回各自最快的方法。

        Args:
            screenshot: 待测试的截图方法名称元组。
            click: 待测试的点击方法名称元组。

        Returns:
            tuple: (最快截图方法, 最快点击方法)。
        """
        logger.hr('Benchmark', level=1)
        logger.info(f'Testing screenshot methods: {screenshot}')
        logger.info(f'Testing click methods: {click}')

        screenshot_result = []
        for method in screenshot:
            result = self.benchmark_test(self.device.screenshot_methods[method])
            screenshot_result.append([method, result])

        area = (124, 4, 649, 106)  # 屏幕上可安全点击的区域
        click_result = []
        for method in click:
            x, y = random_rectangle_point(area)
            result = self.benchmark_test(self.device.click_methods[method], x, y)
            click_result.append([method, result])

        def compare(res):
            res = res[1]
            if not isinstance(res, (int, float)):
                return 100
            else:
                return res

        logger.hr('Benchmark Results', level=1)
        fastest_screenshot = 'ADB_nc'
        fastest_click = 'minitouch'
        if screenshot_result:
            self.show(test='Screenshot', data=screenshot_result, evaluate_func=self.evaluate_screenshot)
            fastest = sorted(screenshot_result, key=lambda item: compare(item))[0]
            logger.info(f'Recommend screenshot method: {fastest[0]} ({float2str(fastest[1])})')
            fastest_screenshot = fastest[0]
        if click_result:
            self.show(test='Control', data=click_result, evaluate_func=self.evaluate_click)
            fastest = sorted(click_result, key=lambda item: compare(item))[0]
            # 如果 minitouch 和 MaaTouch 都是最快的，优先选择 MaaTouch
            if 'MaaTouch' in click and fastest[0] == 'minitouch':
                fastest[0] = 'MaaTouch'
            logger.info(f'Recommend control method: {fastest[0]} ({float2str(fastest[1])})')
            fastest_click = fastest[0]

        return fastest_screenshot, fastest_click

    def get_test_methods(self) -> t.Tuple[t.Tuple[str], t.Tuple[str]]:
        """根据设备类型和 SDK 版本，筛选出可用的截图和点击测试方法。

        Returns:
            tuple: (可用截图方法元组, 可用点击方法元组)。
        """
        device = self.config.Benchmark_DeviceType
        screenshot = ['ADB', 'ADB_nc', 'uiautomator2', 'aScreenCap', 'aScreenCap_nc', 'DroidCast', 'DroidCast_raw']
        click = ['ADB', 'uiautomator2', 'minitouch', 'MaaTouch']

        def remove(*args):
            return [l for l in screenshot if l not in args]

        # Android > 9 不支持 aScreenCap
        sdk = self.device.sdk_ver
        logger.info(f'sdk_ver: {sdk}')
        if not (21 <= sdk <= 28):
            screenshot = remove('aScreenCap', 'aScreenCap_nc')
        # 云手机不支持 nc 本地回环
        if device in ['plone_cloud_with_adb']:
            screenshot = remove('ADB_nc', 'aScreenCap_nc')
        # VMOS 虚拟机仅支持部分方法
        if device == 'android_phone_vmos':
            screenshot = ['ADB', 'aScreenCap', 'DroidCast', 'DroidCast_raw']
            click = ['ADB', 'Hermit', 'MaaTouch']
        # DroidCast 仅支持 SDK 23 (Android 6.0) 到 SDK 32 (Android 12)
        if not (23 <= sdk <= 32):
            screenshot = remove('DroidCast', 'DroidCast_raw')

        if self.device.nemu_ipc_available():
            screenshot.append('nemu_ipc')
        if self.device.ldopengl_available():
            screenshot.append('ldopengl')
        if self.device.is_bluestacks_air:
            screenshot = [l for l in screenshot if 'DroidCast' not in l]

        scene = self.config.Benchmark_TestScene
        if 'screenshot' not in scene:
            screenshot = []
        if 'click' not in scene:
            click = []

        return tuple(screenshot), tuple(click)

    def run(self):
        self.config.override(Emulator_ScreenshotMethod='ADB')
        self.device.uninstall_minicap()
        self.ensure_campaign_ui('7-2', mode='normal')

        logger.attr('DeviceType', self.config.Benchmark_DeviceType)
        logger.attr('TestScene', self.config.Benchmark_TestScene)
        screenshot, click = self.get_test_methods()
        self.benchmark(screenshot, click)

    def run_simple_screenshot_benchmark(self):
        """执行简化版截图基准测试，仅测试 3 次取最优结果。

        用于快速确定当前设备最快的截图方法，测试次数少于完整基准测试。

        Returns:
            str: 当前设备最快的截图方法名称。
        """
        screenshot = ['ADB', 'ADB_nc', 'uiautomator2', 'aScreenCap', 'aScreenCap_nc', 'DroidCast', 'DroidCast_raw']

        def remove(*args):
            return [l for l in screenshot if l not in args]

        sdk = self.device.sdk_ver
        logger.info(f'sdk_ver: {sdk}')
        if not (21 <= sdk <= 28):
            screenshot = remove('aScreenCap', 'aScreenCap_nc')
        if self.device.is_chinac_phone_cloud:
            screenshot = remove('ADB_nc', 'aScreenCap_nc')
        if self.device.nemu_ipc_available():
            screenshot.append('nemu_ipc')
        if self.device.ldopengl_available():
            screenshot.append('ldopengl')
        screenshot = tuple(screenshot)

        self.TEST_TOTAL = 3
        self.TEST_BEST = 1
        method, _ = self.benchmark(screenshot, tuple())

        return method


def run_benchmark(config):
    try:
        Benchmark(config, task='Benchmark').run()
        return True
    except RequestHumanTakeover:
        logger.critical('错误 请求人类接管')
        return False
