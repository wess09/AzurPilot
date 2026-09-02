"""设备输入控制模块。

统一管理所有触控操作（点击、长按、滑动、拖拽），根据配置的控制方法
（ADB、uiautomator2、minitouch、Hermit、MaaTouch、scrcpy、nemu_ipc）
自动分发到对应的底层实现。
"""
from module.base.button import Button
from module.base.decorator import cached_property
from module.base.timer import Timer
from module.base.utils import *
from module.device.method.hermit import Hermit
from module.device.method.maatouch import MaaTouch
from module.device.method.minitouch import Minitouch
from module.device.method.nemu_ipc import NemuIpc
from module.device.method.scrcpy import Scrcpy
from module.logger import logger


class Control(Hermit, Minitouch, Scrcpy, MaaTouch, NemuIpc):
    """设备触控控制调度器。

    通过多重继承组合所有控制后端（Hermit、Minitouch、Scrcpy、MaaTouch、NemuIpc），
    根据用户配置的 Emulator_ControlMethod 自动分发到对应后端实现。
    提供统一的点击、长按、滑动、拖拽接口。
    """
    def handle_control_check(self, button):
        # 将在 Device 中被重写
        pass

    @cached_property
    def click_methods(self):
        """返回控制方法名到点击实现的映射字典。

        Returns:
            dict[str, Callable]: 键为控制方法名（如 'ADB'、'minitouch'），
                值为对应的点击方法。
        """
        return {
            'ADB': self.click_adb,
            'uiautomator2': self.click_uiautomator2,
            'minitouch': self.click_minitouch,
            'Hermit': self.click_hermit,
            'MaaTouch': self.click_maatouch,
            'nemu_ipc': self.click_nemu_ipc,
        }

    def click(self, button, control_check=True):
        """点击按钮。

        Args:
            button (button.Button): 碧蓝航线按钮实例。
            control_check (bool): 是否进行控制检查。
        """
        if control_check:
            self.handle_control_check(button)
        x, y = random_rectangle_point(button.button)
        x, y = ensure_int(x, y)
        logger.info(
            '[设备-控制] 点击 %s @ %s' % (point2str(x, y), button)
        )
        method = self.click_methods.get(
            self.config.Emulator_ControlMethod,
            self.click_adb
        )
        method(x, y)

    def multi_click(self, button, n, interval=(0.1, 0.2)):
        """对按钮执行多次连续点击。

        Args:
            button (button.Button): 碧蓝航线按钮实例。
            n (int): 点击次数。
            interval (tuple): 两次点击之间的间隔范围（秒），格式为 (最小值, 最大值)。
        """
        self.handle_control_check(button)
        click_timer = Timer(0.1)
        for _ in range(n):
            remain = ensure_time(interval) - click_timer.current_time()
            if remain > 0:
                self.sleep(remain)
            click_timer.reset()

            self.click(button, control_check=False)

    def long_click(self, button, duration=(1, 1.2)):
        """长按按钮。

        Args:
            button (button.Button): 碧蓝航线按钮实例。
            duration (int, float, tuple): 长按持续时间。
        """
        self.handle_control_check(button)
        x, y = random_rectangle_point(button.button)
        x, y = ensure_int(x, y)
        duration = ensure_time(duration)
        logger.info(
            '[设备-控制] 长按 %s @ %s, %s' % (point2str(x, y), button, duration)
        )
        method = self.config.Emulator_ControlMethod
        if method == 'minitouch':
            self.long_click_minitouch(x, y, duration)
        elif method == 'uiautomator2':
            self.long_click_uiautomator2(x, y, duration)
        elif method == 'scrcpy':
            self.long_click_scrcpy(x, y, duration)
        elif method == 'MaaTouch':
            self.long_click_maatouch(x, y, duration)
        elif method == 'nemu_ipc':
            self.long_click_nemu_ipc(x, y, duration)
        else:
            self.swipe_adb((x, y), (x, y), duration)

    def swipe(self, p1, p2, duration=(0.1, 0.2), name='SWIPE', distance_check=True):
        """在两点之间执行滑动操作。

        ADB 方式的滑动持续时间会自动乘以 2.5 以保证有效性。
        距离检查会丢弃小于 10 像素的滑动（碧蓝航线会将其视为点击）。

        Args:
            p1 (tuple): 起始坐标 (x, y)。
            p2 (tuple): 终点坐标 (x, y)。
            duration (int, float, tuple): 滑动持续时间（秒）。
            name (str): 滑动操作名称，用于日志输出。
            distance_check (bool): 是否检查滑动距离，距离过小时跳过操作。
        """
        self.handle_control_check(name)
        p1, p2 = ensure_int(p1, p2)
        duration = ensure_time(duration)
        method = self.config.Emulator_ControlMethod
        if method == 'uiautomator2':
            logger.info('[设备-控制] 滑动 %s -> %s, %s' % (point2str(*p1), point2str(*p2), duration))
        elif method in ['minitouch', 'MaaTouch', 'scrcpy', 'nemu_ipc']:
            logger.info('[设备-控制] 滑动 %s -> %s' % (point2str(*p1), point2str(*p2)))
        else:
            # ADB 需要更慢的速度，否则滑动可能无效
            duration *= 2.5
            logger.info('[设备-控制] 滑动 %s -> %s, %s' % (point2str(*p1), point2str(*p2), duration))

        if distance_check:
            if np.linalg.norm(np.subtract(p1, p2)) < 10:
                # 需要滑动一定距离，否则碧蓝航线会将其视为点击
                # uiautomator2 需要 >= 6px，minitouch 需要 >= 5px
                logger.info('[设备-控制] 滑动 距离 < 10px，丢弃')
                return

        if method == 'minitouch':
            self.swipe_minitouch(p1, p2)
        elif method == 'uiautomator2':
            self.swipe_uiautomator2(p1, p2, duration=duration)
        elif method == 'scrcpy':
            self.swipe_scrcpy(p1, p2)
        elif method == 'MaaTouch':
            self.swipe_maatouch(p1, p2)
        elif method == 'nemu_ipc':
            self.swipe_nemu_ipc(p1, p2)
        else:
            self.swipe_adb(p1, p2, duration=duration)

    def swipe_vector(self, vector, box=(123, 159, 1175, 628), random_range=(0, 0, 0, 0), padding=15,
                     duration=(0.1, 0.2), whitelist_area=None, blacklist_area=None, name='SWIPE', distance_check=True):
        """在指定范围内执行向量滑动。

        Args:
            box (tuple): 滑动区域，格式为 (左上角 x, 左上角 y, 右下角 x, 右下角 y)。
            vector (tuple): 滑动向量，格式为 (x, y)。
            random_range (tuple): 随机偏移范围，格式为 (x_min, y_min, x_max, y_max)。
            padding (int): 边距。
            duration (int, float, tuple): 滑动持续时间。
            whitelist_area (list[tuple[int]]): 安全点击区域列表，滑动路径将终止于此。
            blacklist_area (list[tuple[int]]): 当白名单区域无法满足当前向量时使用黑名单区域。
                排除终点在黑名单区域内的随机路径。
            name (str): 滑动名称。
            distance_check (bool): 是否进行距离检查。
        """
        p1, p2 = random_rectangle_vector_opted(
            vector,
            box=box,
            random_range=random_range,
            padding=padding,
            whitelist_area=whitelist_area,
            blacklist_area=blacklist_area
        )
        self.swipe(p1, p2, duration=duration, name=name, distance_check=distance_check)

    def drag(self, p1, p2, segments=1, shake=(0, 15), point_random=(-10, -10, 10, 10), shake_random=(-5, -5, 5, 5),
             swipe_duration=0.25, shake_duration=0.1, hold_duration=0.0, name='DRAG'):
        """执行拖拽操作，支持分段滑动和松手后的抖动模拟。

        用于碧蓝航线中需要精确拖拽的场景（如装备拖放、编队调整）。
        不支持拖拽的后端会回退到 ADB 滑动 + 点击。

        Args:
            p1 (tuple): 起始坐标 (x, y)。
            p2 (tuple): 终点坐标 (x, y)。
            segments (int): 滑动分段数。
            shake (tuple): 松手后的抖动偏移量 (x, y)。
            point_random (tuple): 起点随机偏移范围 (x_min, y_min, x_max, y_max)。
            shake_random (tuple): 抖动的随机偏移范围 (x_min, y_min, x_max, y_max)。
            swipe_duration (float): 滑动持续时间（秒）。
            shake_duration (float): 抖动持续时间（秒）。
            hold_duration (float): 松手前的持续按住时间（秒）。
            name (str): 拖拽操作名称，用于日志输出。
        """
        self.handle_control_check(name)
        p1, p2 = ensure_int(p1, p2)
        logger.info(
            '[设备-控制] 拖拽 %s -> %s' % (point2str(*p1), point2str(*p2))
        )
        method = self.config.Emulator_ControlMethod
        if method == 'minitouch':
            self.drag_minitouch(p1, p2, point_random=point_random, hold_duration=hold_duration)
        elif method == 'uiautomator2':
            self.drag_uiautomator2(
                p1, p2, segments=segments, shake=shake, point_random=point_random, shake_random=shake_random,
                swipe_duration=swipe_duration, shake_duration=shake_duration, hold_duration=hold_duration)
        elif method == 'scrcpy':
            self.drag_scrcpy(p1, p2, point_random=point_random, hold_duration=hold_duration)
        elif method == 'MaaTouch':
            self.drag_maatouch(p1, p2, point_random=point_random, hold_duration=hold_duration)
        elif method == 'nemu_ipc':
            self.drag_nemu_ipc(p1, p2, point_random=point_random, hold_duration=hold_duration)
        else:
            logger.warning(f'[设备-控制] 控制方式 {method} 不支持拖拽，'
                           f'回退到 ADB 滑动可能导致意外行为')
            self.swipe_adb(p1, p2, duration=ensure_time(swipe_duration * 2))
            hold_duration = ensure_time(hold_duration)
            if hold_duration > 0:
                self.sleep(hold_duration)
            self.click(Button(area=(), color=(), button=area_offset(point_random, p2), name=name), False)

    def island_swipe_hold(self, p1, p2, hold_time):
        """岛屿系统专用的滑动并保持操作。

        在两点之间滑动并在终点保持一段时间，用于岛屿内的交互操作。

        Args:
            p1 (tuple): 起始坐标 (x, y)。
            p2 (tuple): 终点坐标 (x, y)。
            hold_time (int, float, tuple): 在终点保持的时间（秒）。
        """
        p1, p2 = ensure_int(p1, p2)
        hold_time = ensure_time(hold_time)
        method = self.config.Emulator_ControlMethod
        if method == 'minitouch':
            self.island_swipe_hold_minitouch(p1, p2, hold_time)