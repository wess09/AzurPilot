# 此文件定义了 Device 类，是脚本与设备交互的综合管理入口。
# 负责整合截图、点击、输入功能，并由于内置了防卡死检测和点击频率控制，能有效提高脚本自动化运行的稳定性。
import collections
import sys
from datetime import datetime

import cv2
from lxml import etree

from module.device.env import IS_WINDOWS, IS_MACINTOSH
# 在导入 adbutils 和 uiautomator2 之前修补 pkg_resources
from module.device.pkg_resources import get_distribution

# 防止被导入优化器移除
_ = get_distribution

from module.base.timer import Timer
from module.config.utils import get_server_next_update
from module.device.app_control import AppControl
from module.device.control import Control
from module.device.input import Input
from module.device.platform import Platform
from module.device.screenshot import Screenshot
from module.exception import (EmulatorNotRunningError, GameNotRunningError, GameStuckError, GameTooManyClickError,
                              RequestHumanTakeover)
from module.handler.assets import GET_MISSION
from module.logger import logger


def show_function_call():
    """
    INFO     21:07:31.554 │ Function calls:
                       <string>   L1 <module>
                   spawn.py L116 spawn_main()
                   spawn.py L129 _main()
                 process.py L314 _bootstrap()
                 process.py L108 run()
         process_manager.py L149 run_process()
                    alas.py L285 loop()
                    alas.py  L69 run()
                     src.py  L55 rogue()
                   rogue.py  L36 run()
                   rogue.py  L18 rogue_once()
                   entry.py L335 rogue_world_enter()
                    path.py L193 rogue_path_select()
    """
    import os
    import traceback
    stack = traceback.extract_stack()
    func_list = []
    for row in stack:
        filename, line_number, function_name, _ = row
        filename = os.path.basename(filename)
        # 示例: /tasks/character/switch.py:64 character_update()
        func_list.append([filename, str(line_number), function_name])
    max_filename = max([len(row[0]) for row in func_list])
    max_linenum = max([len(row[1]) for row in func_list]) + 1

    def format_(file, line, func):
        file = file.rjust(max_filename, " ")
        line = f'L{line}'.rjust(max_linenum, " ")
        if not func.startswith('<'):
            func = f'{func}()'
        return f'{file} {line} {func}'

    func_list = [f'\n{format_(*row)}' for row in func_list]
    logger.info('Function calls:' + ''.join(func_list))


class Device(Screenshot, Control, AppControl, Input):
    """
    设备交互管理类，整合截图、控制、应用管理和输入功能。

    通过多重继承组合 Screenshot、Control、AppControl、Input 四个模块，
    并通过 Platform 委托模拟器管理操作。
    """
    _screen_size_checked = False
    detect_record = set()
    click_record = collections.deque(maxlen=15)
    stuck_timer = Timer(60, count=60).start()
    stuck_timer_long = Timer(195, count=195).start()
    stuck_long_wait_list = ['BATTLE_STATUS_S', 'PAUSE', 'LOGIN_CHECK', 'TEMPLATE_MANJUU']
    _prev_fingerprint = None
    _stuck_image_timer = Timer(30, count=0)

    def __init__(self, *args, **kwargs):
        # 初始化模拟器管理平台
        self._platform = None

        for trial in range(4):
            try:
                super().__init__(*args, **kwargs)
                break
            except EmulatorNotRunningError:
                if trial >= 3:
                    logger.critical('错误 3 次尝试后未能启动模拟器')
                    raise RequestHumanTakeover
                # 尝试启动模拟器
                if self.emulator_instance is not None:
                    self.emulator_start()
                else:
                    logger.critical(
                        f'错误 未找到序列号为 "{self.config.Emulator_Serial}" 的模拟器，'
                        f'请设置一个正确的序列号'
                    )
                    raise RequestHumanTakeover

        # 确保 package 属性存在（部分连接模式可能不会设置它）
        # AppControl.app_is_running() 会用到此属性
        if not hasattr(self, 'package'):
            # 回退到配置值；如果是 'auto'，后续检测会更新它
            self.package = getattr(self.config, 'Emulator_PackageName', 'auto')

        # 自动填充模拟器信息
        if IS_WINDOWS and self.config.EmulatorInfo_Emulator == 'auto':
            _ = self.emulator_instance

        # Mac 上提升运行中模拟器的优先级
        if IS_MACINTOSH:
            try:
                self.platform.boost_running_emulator_priority()
            except Exception as e:
                logger.warning(f'Failed to boost emulator priority: {e}')

        self.screenshot_interval_set()
        self.method_check()

        # 自动选择最快的截图方式
        if not self.config.is_template_config and self.config.Emulator_ScreenshotMethod == 'auto':
            self.run_simple_screenshot_benchmark()
        # 自动选择 OCR 设备
        if not self.config.is_template_config and self.config.Optimization_OcrDevice == 'auto':
            self.run_simple_ocr_benchmark()

        # 提前初始化控制方式
        if self.config.is_actual_task:
            if self.config.Emulator_ControlMethod == 'MaaTouch':
                self.early_maatouch_init()
            if self.config.Emulator_ControlMethod == 'minitouch':
                self.early_minitouch_init()

    @property
    def platform(self):
        """
        获取模拟器管理平台实例。

        惰性初始化，首次访问时创建 Platform 实例。
        """
        if self._platform is None:
            # 当模拟器离线时（通常是需要自动启动的场景），
            # 必须避免在此触发完整的 ADB 连接，否则 Platform 会再次抛出
            # EmulatorNotRunningError，而此时 Device.__init__ 正在处理该异常。
            #
            # 因此使用 connect=False 构造 Platform，仅执行轻量初始化
            # （config/adb_client/serial），足以发现 emulator_instance 和
            # 调用 emulator_start()；真正的 ADB 连接在 Device 初始化完成后
            # 由 Connection 完成。
            self._platform = Platform(self.config, connect=False)
        return self._platform

    @property
    def emulator_instance(self):
        """
        获取当前模拟器实例。

        Returns:
            模拟器实例对象，未找到时返回 None。
        """
        return self.platform.emulator_instance

    def emulator_start(self):
        """
        启动模拟器，委托给平台特定实现。
        """
        return self.platform.emulator_start()

    def emulator_stop(self):
        """
        停止模拟器，委托给平台特定实现。
        """
        return self.platform.emulator_stop()

    def run_simple_screenshot_benchmark(self):
        """
        运行截图方式基准测试，每种方式测试 3 次，选择最快的写入配置。
        """
        logger.info('run_simple_screenshot_benchmark')
        # 先检查分辨率
        self.resolution_check_uiautomator2()
        # 执行基准测试
        from module.daemon.benchmark import Benchmark
        bench = Benchmark(config=self.config, device=self)
        method = bench.run_simple_screenshot_benchmark()
        # 写入配置
        with self.config.multi_set():
            self.config.Emulator_ScreenshotMethod = method
            # if method == 'nemu_ipc':
            #     self.config.Emulator_ControlMethod = 'nemu_ipc'

    def run_simple_ocr_benchmark(self):
        """
        运行 OCR 设备基准测试，优先测试 GPU。

        准确率 100% 则选择 'gpu'，否则回退到 'cpu'。
        """
        logger.info('run_simple_ocr_benchmark')
        from module.daemon.ocr_benchmark import OcrBenchmark
        bench = OcrBenchmark(config=self.config, device=self)
        device = bench.run_simple_ocr_benchmark()
        # 写入配置
        with self.config.multi_set():
            self.config.Optimization_OcrDevice = device
            # 写入配置后需要重新执行 reset_ocr_model()。
            # 因为 run_simple_ocr_benchmark() 内部会覆盖并调用 reset，
            # 必须确保最终状态与刚保存的配置一致。
            from module.ocr.al_ocr import reset_ocr_model
            reset_ocr_model()

    def method_check(self):
        """
        检查截图方式和控制方式的组合是否合法。
        """
        # nemu_ipc 截图和控制必须配套使用
        # if self.config.Emulator_ScreenshotMethod == 'nemu_ipc' and self.config.Emulator_ControlMethod != 'nemu_ipc':
        #     logger.warning('When using nemu_ipc, both screenshot and control should use nemu_ipc')
        #     self.config.Emulator_ControlMethod = 'nemu_ipc'
        # if self.config.Emulator_ScreenshotMethod != 'nemu_ipc' and self.config.Emulator_ControlMethod == 'nemu_ipc':
        #     logger.warning('When not using nemu_ipc, both screenshot and control should not use nemu_ipc')
        #     self.config.Emulator_ControlMethod = 'minitouch'
        # Hermit 仅允许在 VMOS 上使用
        if self.config.Emulator_ControlMethod == 'Hermit' and not self.is_vmos:
            logger.warning('ControlMethod Hermit is allowed on VMOS only')
            self.config.Emulator_ControlMethod = 'MaaTouch'
        if self.config.Emulator_ScreenshotMethod == 'ldopengl' \
                and self.config.Emulator_ControlMethod == 'minitouch':
            logger.warning('Use MaaTouch on ldplayer')
            self.config.Emulator_ControlMethod = 'MaaTouch'

        # nemu_ipc 和 ldopengl 在非对应模拟器上回退到 auto
        if self.config.Emulator_ScreenshotMethod == 'nemu_ipc':
            if not (self.is_emulator and self.is_mumu_family):
                logger.warning('ScreenshotMethod nemu_ipc is available on MuMu Player 12 only, fallback to auto')
                self.config.Emulator_ScreenshotMethod = 'auto'
        if self.config.Emulator_ScreenshotMethod == 'ldopengl':
            if not (self.is_emulator and self.is_ldplayer_bluestacks_family):
                logger.warning('ScreenshotMethod ldopengl is available on LD Player only, fallback to auto')
                self.config.Emulator_ScreenshotMethod = 'auto'
        if not IS_WINDOWS and self.config.Emulator_ScreenshotMethod in ['nemu_ipc', 'ldopengl']:
            logger.warning(f'ScreenshotMethod {self.config.Emulator_ScreenshotMethod} is available on Windows only, '
                           f'fallback to auto')
            self.config.Emulator_ScreenshotMethod = 'auto'

    def handle_night_commission(self, daily_trigger='21:00', threshold=30):
        """
        检测并处理夜间委托刷新弹窗。

        Args:
            daily_trigger: 委托刷新时间点。
            threshold: 刷新时间前后多少秒内触发检测。

        Returns:
            是否点击了委托弹窗。
        """
        update = get_server_next_update(daily_trigger=daily_trigger)
        now = datetime.now()
        diff = (update.timestamp() - now.timestamp()) % 86400
        if threshold < diff < 86400 - threshold:
            return False

        if GET_MISSION.match(self.image, offset=True):
            logger.info('Night commission appear.')
            self.click(GET_MISSION)
            return True

        return False

    def screenshot(self):
        """
        截取屏幕截图，包含卡死检测和夜间委托处理。

        Returns:
            截图图像，numpy 数组格式。
        """
        self.stuck_record_check()

        try:
            super().screenshot()
        except RequestHumanTakeover:
            if not self.ascreencap_available:
                logger.error('aScreenCap unavailable on current device, fallback to auto')
                self.run_simple_screenshot_benchmark()
                super().screenshot()
            else:
                raise

        if self.handle_night_commission():
            super().screenshot()

        self._check_image_stuck()
        return self.image

    def dump_hierarchy(self) -> etree._Element:
        self.stuck_record_check()
        return super().dump_hierarchy()

    def release_during_wait(self):
        """
        等待期间释放截图资源，避免后台持续占用。
        """
        # Scrcpy 服务端持续发送视频流，等待期间需要停止
        if self.config.Emulator_ScreenshotMethod == 'scrcpy':
            self._scrcpy_server_stop()
        if self.config.Emulator_ScreenshotMethod == 'nemu_ipc':
            self.nemu_ipc_release()

    def get_orientation(self):
        """
        获取屏幕方向，方向变化时触发回调。
        """
        o = super().get_orientation()

        self.on_orientation_change_maatouch()

        return o

    def stuck_record_add(self, button):
        self.detect_record.add(str(button))

    def stuck_record_clear(self):
        self.detect_record = set()
        self.stuck_timer.reset()
        self.stuck_timer_long.reset()
        self._stuck_image_timer.clear()

    def _check_image_stuck(self):
        if self.image is None:
            return

        small = cv2.resize(self.image, (16, 16))
        fp = hash(small.tobytes())

        if self._prev_fingerprint is not None and fp == self._prev_fingerprint:
            self._stuck_image_timer.start()
            if self._stuck_image_timer.reached():
                show_function_call()
                logger.warning(f'Screenshot unchanged for over {self._stuck_image_timer.limit}s')
                self.stuck_record_clear()
                if self.app_is_running():
                    raise GameStuckError('Screenshot not changing')
                else:
                    raise GameNotRunningError('Game died')
        else:
            self._prev_fingerprint = fp
            self._stuck_image_timer.clear()

    def stuck_record_check(self):
        """
        检查是否卡死（操作超时或长时间无有效截图操作）。

        Raises:
            GameStuckError: 游戏卡死。
            GameNotRunningError: 游戏已退出。
        """
        reached = self.stuck_timer.reached()
        reached_long = self.stuck_timer_long.reached()

        if not reached:
            return False
        if not reached_long:
            for button in self.stuck_long_wait_list:
                if button in self.detect_record:
                    return False

        show_function_call()
        logger.warning('Wait too long')
        logger.warning(f'Waiting for {self.detect_record}')
        self.stuck_record_clear()

        if self.app_is_running():
            raise GameStuckError(f'Wait too long')
        else:
            raise GameNotRunningError('Game died')

    def handle_control_check(self, button):
        self.stuck_record_clear()
        self.click_record_add(button)
        self.click_record_check()

    def click_record_add(self, button):
        self.click_record.append(str(button))

    def click_record_clear(self):
        self.click_record.clear()

    def click_record_remove(self, button):
        """
        从点击记录中移除指定按钮的所有记录。

        Args:
            button: 要移除的按钮对象。

        Returns:
            移除的记录数量。
        """
        removed = 0
        for _ in range(self.click_record.maxlen):
            try:
                self.click_record.remove(str(button))
                removed += 1
            except ValueError:
                # 队列中已无该值
                break

        return removed

    def click_record_check(self):
        """
        检查点击频率是否异常（同一按钮被点击过多或两个按钮交替点击过多）。

        Raises:
            GameTooManyClickError: 点击频率异常。
        """
        count = collections.Counter(self.click_record).most_common(2)
        if count[0][1] >= 12:
            show_function_call()
            logger.warning(f'Too many click for a button: {count[0][0]}')
            logger.warning(f'History click: {[str(prev) for prev in self.click_record]}')
            self.click_record_clear()
            raise GameTooManyClickError(f'Too many click for a button: {count[0][0]}')
        if len(count) >= 2 and count[0][1] >= 6 and count[1][1] >= 6:
            show_function_call()
            logger.warning(f'Too many click between 2 buttons: {count[0][0]}, {count[1][0]}')
            logger.warning(f'History click: {[str(prev) for prev in self.click_record]}')
            self.click_record_clear()
            raise GameTooManyClickError(f'Too many click between 2 buttons: {count[0][0]}, {count[1][0]}')

    def disable_stuck_detection(self):
        """
        禁用卡死检测，用于半自动模式和调试场景。
        """
        logger.info('Disable stuck detection')

        def empty_function(*arg, **kwargs):
            return False

        self.click_record_check = empty_function
        self.stuck_record_check = empty_function

    def app_start(self):
        if not self.config.Error_HandleError:
            logger.critical('错误 没有启动/停止应用，因为 HandleError 已禁用')
            logger.critical('请启用 Alas.Error.HandleError 或手动登录碧蓝航线')
            raise RequestHumanTakeover
        super().app_start()
        self.stuck_record_clear()
        self.click_record_clear()

    def app_stop(self):
        if not self.config.Error_HandleError:
            logger.critical('错误 没有启动/停止应用，因为 HandleError 已禁用')
            logger.critical('请启用 Alas.Error.HandleError 或手动登录碧蓝航线')
            raise RequestHumanTakeover
        super().app_stop()
        self.stuck_record_clear()
        self.click_record_clear()
