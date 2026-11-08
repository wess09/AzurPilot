"""基准测试模块。

用于评估设备性能，包括截图速度、图像处理速度和战斗效率。
使用 Rich 表格输出测试结果，帮助用户选择最佳的截图后端配置。
"""

import time
import typing as t

import cv2
import numpy as np
from rich.table import Table
from rich.text import Text

from module.base.decorator import cached_property
from module.base.utils import float2str as float2str_
from module.base.utils import random_rectangle_point
from module.campaign.campaign_ui import CampaignUI
from module.daemon.daemon_base import DaemonBase
from module.exception import RequestHumanTakeover
from module.logger import logger

# 框架入口先加载 Device 并注册 pkg_resources 兼容层，随后才能加载 u2/adbutils。
import uiautomator2 as u2


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
    U2_PROBE_TIMEOUT = (3, 5)

    @cached_property
    def _u2_benchmark_client(self):
        """测速不经过设备 u2 属性的 keepalive 初始化，避免触发 agent 安装恢复。"""
        serial = self.device.serial
        if serial.startswith(('emulator-', '127.0.0.1:')):
            return u2.connect_usb(serial)
        return u2.connect(serial)

    def _benchmark_u2_screenshot(self):
        """限时尝试已有截图服务，失败交给测速层跳过，不进入后端多轮重试。"""
        with self._u2_benchmark_client.http.get(
                '/screenshot/0', timeout=self.U2_PROBE_TIMEOUT, retry=False) as response:
            response.raise_for_status()
            image = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError('uiautomator2 测速截图无效')
        return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    @cached_property
    def _u2_benchmark_click_client(self):
        """点击还需要 uiautomator 服务；仅启动已有服务一次，限时确认就绪。"""
        client = self._u2_benchmark_client
        with client.http.get('/services/uiautomator', timeout=self.U2_PROBE_TIMEOUT, retry=False) as response:
            response.raise_for_status()
            if response.json().get('running'):
                return client
        with client.http.post('/services/uiautomator', timeout=self.U2_PROBE_TIMEOUT, retry=False) as response:
            response.raise_for_status()

        deadline = time.monotonic() + self.U2_PROBE_TIMEOUT[1]
        payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'deviceInfo', 'params': []}
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('uiautomator2 测速点击服务启动超时')
            timeout = tuple(min(limit, remaining) for limit in self.U2_PROBE_TIMEOUT)
            with client.http.post('/jsonrpc/0', json=payload, timeout=timeout, retry=False) as response:
                # 进程启动到 RPC 端口就绪之间，atx-agent 暂时返回 502。
                if response.status_code != 502:
                    response.raise_for_status()
                    result = response.json()
                    if result.get('error') is not None:
                        raise RuntimeError(f'uiautomator2 测速服务启动失败: {result["error"]}')
                    return client
            time.sleep(min(0.1, remaining))

    def _benchmark_u2_click(self, x, y):
        """完整测速中的 u2 点击同样只尝试一次，不触发 JSON-RPC 自动恢复。"""
        payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'click', 'params': [x, y]}
        with self._u2_benchmark_click_client.http.post(
                '/jsonrpc/0', json=payload, timeout=self.U2_PROBE_TIMEOUT, retry=False) as response:
            response.raise_for_status()
            result = response.json()
        if result.get('error') is not None:
            raise RuntimeError(f'uiautomator2 测速点击失败: {result["error"]}')
        return result['result']

    def benchmark_test(self, func, *args, quiet=False, **kwargs):
        """对指定函数执行多次基准测试，返回平均耗时。

        连续调用 func TEST_TOTAL 次，去掉最慢的 20% 结果后取平均值。
        若中途出现 RequestHumanTakeover 或其他异常则立即返回 'Failed'。

        Args:
            func: 待测试的函数。
            *args: 传递给 func 的位置参数。
            quiet: 为 True 时（auto 探测路径）探测失败只打一行警告，
                不打印整段 traceback；失败只跳过本次测速候选。
            **kwargs: 传递给 func 的关键字参数。

        Returns:
            float: 去除异常值后的平均耗时（秒），失败时返回 'Failed'。

        Raises:
            RequestHumanTakeover: 不捕获此异常，直接向上抛出。
        """
        logger.hr(f'基准测试', level=2)
        logger.info(f'测试函数: {func.__name__}')
        record = []

        for n in range(1, self.TEST_TOTAL + 1):
            start = time.perf_counter()

            try:
                func(*args, **kwargs)
            except RequestHumanTakeover:
                logger.critical('[Daemon] 错误 请求人类接管')
                logger.warning(f'[守护-基准测试] 基准测试失败，函数: {func.__name__}')
                return 'Failed'
            except Exception as e:
                if quiet:
                    logger.warning(
                        f'[守护-基准测试] {func.__name__}() 探测失败，跳过该候选后端: '
                        f'{type(e).__name__}: {e}'
                    )
                else:
                    logger.exception(e)
                logger.warning(f'[守护-基准测试] 基准测试失败，函数: {func.__name__}')
                return 'Failed'

            cost = time.perf_counter() - start
            logger.attr(
                f'{str(n).rjust(2, "0")}/{self.TEST_TOTAL}',
                f'{float2str(cost)}'
            )
            record.append(cost)

        logger.info('基准测试完成')
        average = float(np.mean(np.sort(record)[:self.TEST_BEST]))
        logger.info(f'[守护-基准测试] 耗时 {float2str(average)} (最优 {self.TEST_BEST} 次，共 {self.TEST_TOTAL} 次测试)')
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
    def evaluate_ping(cost):
        """根据特权桥通信 RTT 耗时评估速度等级。

        Args:
            cost: 通信往返耗时（秒），非数值时表示失败。

        Returns:
            Text: 带颜色标签的速度描述文本。
        """
        if not isinstance(cost, (float, int)):
            return Text(str(cost), style="bold bright_red")

        if cost < 0.002:
            return Text('Insane Fast', style="bold bright_green")
        if cost < 0.005:
            return Text('Ultra Fast', style="bold bright_green")
        if cost < 0.010:
            return Text('Very Fast', style="bright_green")
        if cost < 0.020:
            return Text('Fast', style="green")
        if cost < 0.050:
            return Text('Medium', style="yellow")
        return Text('Slow', style="red")

    @staticmethod
    def evaluate_fps(fps):
        """根据截图吞吐帧率评估性能等级。

        Args:
            fps: 吞吐帧率 (FPS)。

        Returns:
            Text: 带颜色标签的性能描述文本。
        """
        if not isinstance(fps, (float, int)):
            return Text(str(fps), style="bold bright_red")

        if fps >= 40.0:
            return Text('Insane Fast', style="bold bright_green")
        if fps >= 25.0:
            return Text('Ultra Fast', style="bold bright_green")
        if fps >= 15.0:
            return Text('Very Fast', style="bright_green")
        if fps >= 10.0:
            return Text('Fast', style="green")
        return Text('Medium', style="yellow")

    @staticmethod
    def evaluate_bandwidth(bw_mb):
        """根据回环数据传输带宽评估性能等级。

        Args:
            bw_mb: 回环带宽吞吐 (MB/s)。

        Returns:
            Text: 带颜色标签的带宽描述文本。
        """
        if not isinstance(bw_mb, (float, int)):
            return Text(str(bw_mb), style="bold bright_red")

        if bw_mb >= 100.0:
            return Text('Insane High', style="bold bright_green")
        if bw_mb >= 60.0:
            return Text('Ultra High', style="bold bright_green")
        if bw_mb >= 30.0:
            return Text('Very High', style="bright_green")
        if bw_mb >= 15.0:
            return Text('High', style="green")
        return Text('Medium', style="yellow")

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

    def benchmark(self, screenshot: t.Tuple[str] = (), click: t.Tuple[str] = (), quiet: bool = False):
        """执行截图和点击方法的基准测试，返回各自最快的方法。

        Args:
            screenshot: 待测试的截图方法名称元组。
            click: 待测试的点击方法名称元组。
            quiet: 传给 ``benchmark_test``，auto 探测路径为 True，失败静默降级。

        Returns:
            tuple: (最快截图方法, 最快点击方法)。
        """
        logger.hr('基准测试', level=1)
        logger.info(f'测试截图方案: {screenshot}')
        logger.info(f'测试控制方案: {click}')

        screenshot_result = []
        for method in screenshot:
            func = self._benchmark_u2_screenshot if method == 'uiautomator2' else self.device.screenshot_methods[method]
            result = self.benchmark_test(func, quiet=quiet)
            screenshot_result.append([method, result])

        area = (124, 4, 649, 106)  # 屏幕上可安全点击的区域
        click_result = []
        for method in click:
            x, y = random_rectangle_point(area)
            func = self._benchmark_u2_click if method == 'uiautomator2' else self.device.click_methods[method]
            result = self.benchmark_test(func, x, y, quiet=quiet)
            click_result.append([method, result])

        def compare(res):
            res = res[1]
            if not isinstance(res, (int, float)):
                return 100
            else:
                return res

        logger.hr('基准测试结果', level=1)
        fastest_screenshot = 'ADB_nc'
        fastest_click = 'minitouch'
        if screenshot_result:
            self.show(test='Screenshot', data=screenshot_result, evaluate_func=self.evaluate_screenshot)
            fastest = sorted(screenshot_result, key=lambda item: compare(item))[0]
            logger.info(f'推荐截图方案: {fastest[0]} ({float2str(fastest[1])})')
            fastest_screenshot = fastest[0]
        if click_result:
            self.show(test='Control', data=click_result, evaluate_func=self.evaluate_click)
            fastest = sorted(click_result, key=lambda item: compare(item))[0]
            # 如果 minitouch 和 MaaTouch 都是最快的，优先选择 MaaTouch；
            # nemu_ipc 触控有兼容性风险，不作推荐，同为最快时也让位 MaaTouch
            if 'MaaTouch' in click and fastest[0] in ('minitouch', 'nemu_ipc'):
                fastest[0] = 'MaaTouch'
            logger.info(f'推荐控制方案: {fastest[0]} ({float2str(fastest[1])})')
            fastest_click = fastest[0]

        return fastest_screenshot, fastest_click

    @property
    def is_virtual_display(self) -> bool:
        """判断当前运行环境是否为 Android 虚拟屏（azurpilot_android）。

        Returns:
            bool: 处于虚拟屏环境返回 True。
        """
        serial = getattr(self.device, 'serial', '') or ''
        return (
            serial.startswith('azurpilot_android')
            or self.config.Benchmark_DeviceType == 'azurpilot_android'
            or self.config.Emulator_ScreenshotMethod == 'azurpilot_android'
            or self.config.Emulator_ControlMethod == 'azurpilot_android'
        )

    def get_test_methods(self) -> t.Tuple[t.Tuple[str], t.Tuple[str]]:
        """根据设备类型和 SDK 版本，筛选出可用的截图和点击测试方法。

        Returns:
            tuple: (可用截图方法元组, 可用点击方法元组)。
        """
        device = self.config.Benchmark_DeviceType

        if self.is_virtual_display:
            screenshot = ['azurpilot_android']
            click = ['azurpilot_android']
            scene = self.config.Benchmark_TestScene
            if 'screenshot' not in scene:
                screenshot = []
            if 'click' not in scene:
                click = []
            return tuple(screenshot), tuple(click)

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
            # nemu_ipc 也实现了点击（Control.click_methods 已注册），完整基准测试
            # 中展示其成绩供参考；自动选择路径（run_simple_screenshot_benchmark）
            # 不包含 nemu_ipc，不会自动启用
            click.append('nemu_ipc')
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
        """执行完整基准测试任务，评估当前配置下的所有可用截图与点击方法。"""
        if not self.is_virtual_display:
            self.config.override(Emulator_ScreenshotMethod='ADB')
            self.device.uninstall_minicap()
        self.ensure_campaign_ui('7-2', mode='normal')

        logger.attr('设备类型', self.config.Benchmark_DeviceType)
        logger.attr('测试场景', self.config.Benchmark_TestScene)
        screenshot, click = self.get_test_methods()
        self.benchmark(screenshot, click)

        if self.is_virtual_display:
            self.benchmark_virtual_display()

    def run_simple_screenshot_benchmark(self):
        """执行简化版截图基准测试，仅测试 3 次取最优结果。

        用于快速确定当前设备最快的截图方法，测试次数少于完整基准测试。

        Returns:
            str: 当前设备最快的截图方法名称。
        """
        if self.is_virtual_display:
            logger.info('[守护-基准测试] 运行环境为 Android 虚拟屏，固定使用 azurpilot_android')
            return 'azurpilot_android'

        screenshot = ['ADB', 'ADB_nc', 'uiautomator2', 'aScreenCap', 'aScreenCap_nc', 'DroidCast', 'DroidCast_raw']

        def remove(*args):
            return [l for l in screenshot if l not in args]

        sdk = self.device.sdk_ver
        logger.info(f'sdk_ver: {sdk}')
        if not (21 <= sdk <= 28):
            screenshot = remove('aScreenCap', 'aScreenCap_nc')
        if not (23 <= sdk <= 32):
            screenshot = remove('DroidCast', 'DroidCast_raw')
        if self.device.is_chinac_phone_cloud:
            screenshot = remove('ADB_nc', 'aScreenCap_nc')
        # 注意：nemu_ipc 不参与自动选择（速度虽快但触控有兼容性风险），
        # 仅在完整基准测试（get_test_methods）中展示成绩，由用户手动决定是否启用
        if self.device.ldopengl_available():
            screenshot.append('ldopengl')
        screenshot = tuple(screenshot)

        self.TEST_TOTAL = 3
        self.TEST_BEST = 1
        # 保留 u2 测速候选；探测异常或超时只跳过本次候选，不按系统版本提前排除。
        method, _ = self.benchmark(screenshot, tuple(), quiet=True)

        return method

    def benchmark_virtual_display(self, rounds: int = 15):
        """执行 Android 虚拟屏专用性能基准测试。

        评测桥接往返 RTT、全分辨率单帧截图耗时、极限连续捕获吞吐 (FPS)、
        回环传输数据带宽 (MB/s)、触控与滑动注入耗时、以及画面帧递增健康度。

        Args:
            rounds (int): 测试轮数，默认 15 次。
        """
        logger.hr('Android 虚拟屏性能基准测试', level=1)

        # 1. Ping RTT 测试
        logger.info('正在测试特权桥通信 RTT (Ping)...')
        ping_records = []
        ping_info = {}
        for _ in range(rounds):
            t0 = time.perf_counter()
            try:
                resp = self.device._azurpilot_android_call_ok({'method': 'ping'})
                ping_records.append(time.perf_counter() - t0)
                if not ping_info and isinstance(resp, dict):
                    ping_info = resp
            except Exception as e:
                logger.warning(f'Ping 测试异常: {e}')

        best_n = max(1, int(len(ping_records) * 0.8))
        avg_ping = float(np.mean(np.sort(ping_records)[:best_n])) if ping_records else 'Failed'

        # 2. 连续极速截图吞吐 (Saturated FPS & Bandwidth)
        logger.info('正在测试虚拟屏极限连拍吞吐与回环带宽...')
        sc_records = []
        frames_tracked = []
        saturated_start = time.perf_counter()
        captured_count = 0
        for _ in range(rounds):
            t0 = time.perf_counter()
            try:
                with self.device._azurpilot_android_lock:
                    resp = self.device._azurpilot_android_call_ok({'method': 'screencap'})
                    raw = self.device._azurpilot_android_read_exact(int(resp['length']))
                    if 'frames' in resp:
                        frames_tracked.append(resp['frames'])
                w, h, c = int(resp['width']), int(resp['height']), int(resp['channels'])
                _ = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, c)
                sc_records.append(time.perf_counter() - t0)
                captured_count += 1
            except Exception as e:
                logger.warning(f'连拍测试异常: {e}')
                break

        saturated_total_time = time.perf_counter() - saturated_start
        sc_best_n = max(1, int(len(sc_records) * 0.8))
        avg_sc = float(np.mean(np.sort(sc_records)[:sc_best_n])) if sc_records else 'Failed'

        if captured_count > 0 and saturated_total_time > 0:
            fps = float(captured_count / saturated_total_time)
            # 单帧 1280*720*3 字节 = 2,764,800 bytes
            bytes_per_frame = 1280 * 720 * 3
            bandwidth_mb = float((captured_count * bytes_per_frame) / (1024 * 1024 * saturated_total_time))
        else:
            fps = 'Failed'
            bandwidth_mb = 'Failed'

        # 3. 触控与手势注入延迟 (安全区域点击与小行程滑动)
        logger.info('正在测试特权桥输入注入延迟 (Click & Swipe)...')
        click_records = []
        safe_x, safe_y = 200, 20
        scene = self.config.Benchmark_TestScene
        if 'click' in scene:
            for _ in range(min(5, rounds)):
                t0 = time.perf_counter()
                try:
                    self.device.click_azurpilot_android(safe_x, safe_y)
                    click_records.append(time.perf_counter() - t0)
                except Exception as e:
                    logger.warning(f'点击测试异常: {e}')
                    break

            avg_click = float(np.mean(click_records)) if click_records else 'Failed'

            swipe_records = []
            for _ in range(min(5, rounds)):
                t0 = time.perf_counter()
                try:
                    self.device.swipe_azurpilot_android((safe_x, safe_y), (safe_x + 15, safe_y), duration=0.05)
                    swipe_records.append(time.perf_counter() - t0)
                except Exception as e:
                    logger.warning(f'滑动测试异常: {e}')
                    break

            avg_swipe = float(np.mean(swipe_records)) if swipe_records else 'Failed'
        else:
            avg_click = 'Skipped'
            avg_swipe = 'Skipped'

        # 4. 画面新鲜度与帧递增健康度 (Surface Freshness)
        if len(frames_tracked) >= 2:
            frame_delta = frames_tracked[-1] - frames_tracked[0]
            if frame_delta > 0:
                freshness_status = f'活跃 (+{frame_delta} 帧)'
                freshness_rating = Text('Healthy', style='bold bright_green')
                freshness_desc = f'ImageReader 正在持续推送新帧 (序号 {frames_tracked[0]} -> {frames_tracked[-1]})'
            else:
                freshness_status = f'静止 (+0 帧)'
                freshness_rating = Text('Static', style='yellow')
                freshness_desc = f'画面内容无变化或已被 ROM 节电冻结 (序号恒为 {frames_tracked[0]})'
        else:
            freshness_status = '未知'
            freshness_rating = Text('N/A', style='white')
            freshness_desc = '未采集到有效帧计数'

        # 5. 格式化输出 Rich 报告表格
        table = Table(
            title='Android 虚拟屏性能综合评测 (Virtual Display Benchmark)',
            show_lines=True,
            header_style='bold bright_cyan',
        )
        table.add_column('指标项 (Metric)', style='cyan', no_wrap=True)
        table.add_column('实测数值 (Value)', style='magenta', justify='right')
        table.add_column('评级 (Rating)', justify='center')
        table.add_column('详细说明 (Architecture Notes)', style='white')

        ping_desc = '127.0.0.1:22301 本地回环通信'
        if 'displayId' in ping_info:
            ping_desc += f' (VirtualDisplay ID={ping_info["displayId"]})'
        table.add_row('Bridge Ping RTT', f"{avg_ping * 1000:.2f} ms" if isinstance(avg_ping, (int, float)) else str(avg_ping), self.evaluate_ping(avg_ping), ping_desc)

        table.add_row('Screencap Latency', f"{avg_sc * 1000:.2f} ms" if isinstance(avg_sc, (int, float)) else str(avg_sc), self.evaluate_screenshot(avg_sc), '1280x720 RGB 单帧截取、读取及解析耗时')

        table.add_row('Saturated FPS', f"{fps:.1f} FPS" if isinstance(fps, (int, float)) else str(fps), self.evaluate_fps(fps), '无间隔连续抓帧极限吞吐能力')

        table.add_row('Loopback Bandwidth', f"{bandwidth_mb:.1f} MB/s" if isinstance(bandwidth_mb, (int, float)) else str(bandwidth_mb), self.evaluate_bandwidth(bandwidth_mb), 'Linux 内核套接字纯内存缓冲传输 (零闪存磨损)')

        if 'click' in scene:
            click_overhead = f"含特权桥标称 50ms 保持 (净开销 ~{max(0.0, avg_click * 1000 - 50):.1f}ms)" if isinstance(avg_click, (int, float)) else "触控点击注入异常"
            table.add_row('Click Latency', f"{avg_click * 1000:.2f} ms" if isinstance(avg_click, (int, float)) else str(avg_click), self.evaluate_click(avg_click), click_overhead)

            swipe_overhead = f"含手势标称 50ms 时长 (净开销 ~{max(0.0, avg_swipe * 1000 - 50):.1f}ms)" if isinstance(avg_swipe, (int, float)) else "手势滑动注入异常"
            table.add_row('Swipe Latency', f"{avg_swipe * 1000:.2f} ms" if isinstance(avg_swipe, (int, float)) else str(avg_swipe), self.evaluate_click(avg_swipe), swipe_overhead)

        table.add_row('Surface Freshness', freshness_status, freshness_rating, freshness_desc)

        logger.print(table, justify='center')
        logger.info('Android 虚拟屏专项基准测试完成')


def run_benchmark(config):
    """运行基准测试任务入口函数。

    Args:
        config (AzurLaneConfig): 配置实例。

    Returns:
        bool: 测试成功返回 True，请求人类接管等异常返回 False。
    """
    try:
        Benchmark(config, task='Benchmark').run()
        return True
    except RequestHumanTakeover:
        logger.critical('[Daemon] 错误 请求人类接管')
        return False
