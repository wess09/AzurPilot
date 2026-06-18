from typing import Tuple, Union

from module.base.button import Button
from module.base.decorator import cached_property
# 此文件定义了 Alas 逻辑模块的最高基类 ModuleBase。
# 作为所有具体功能模块（如出击、大世界、每日任务等）的公共祖先，它整合了 UI 导航、任务循环控制及基本异常处理逻辑。
from module.base.timer import Timer
from module.base.utils import *
from module.combat.emotion import Emotion
from module.config.config import AzurLaneConfig
from module.config.server import set_server, to_package
from module.device.device import Device
from module.device.method.utils import HierarchyButton
from module.logger import logger
from module.map_detection.utils import fit_points
from module.statistics.azurstats import AzurStats
from module.webui.setting import cached_class_property


class ModuleBase:
    config: AzurLaneConfig
    device: Device

    EARLY_OCR_IMPORT = False

    def __init__(self, config, device=None, task=None):
        """
        初始化模块基类，绑定配置和设备。

        Args:
            config: 配置对象或配置名称。
                传入 AzurLaneConfig 实例直接使用，传入 str 则从 ./config/ 下加载。
            device: 设备对象、设备序列号或 None。
                传入 Device 实例复用已有设备，传入 str 以指定模拟器序列号，
                None 则自动创建新设备。
            task: 绑定的任务名称，仅用于开发调试。
                自动调度时通常为 None，使用默认配置。
        """
        if isinstance(config, AzurLaneConfig):
            self.config = config
            if task is not None:
                self.config.init_task(task)
        elif isinstance(config, str):
            self.config = AzurLaneConfig(config, task=task)
        else:
            logger.warning('Alas ModuleBase received an unknown config, assume it is AzurLaneConfig')
            self.config = config

        if isinstance(device, Device):
            self.device = device
        elif device is None:
            self.device = Device(config=self.config)
        elif isinstance(device, str):
            self.config.override(Emulator_Serial=device)
            self.device = Device(config=self.config)
        else:
            logger.warning('Alas ModuleBase received an unknown device, assume it is Device')
            self.device = device

        self.interval_timer = {}
        self.early_ocr_import()

    @cached_property
    def stat(self) -> AzurStats:
        return AzurStats(config=self.config)

    @cached_property
    def emotion(self) -> Emotion:
        return Emotion(config=self.config)

    def early_ocr_import(self):
        """
        异步预导入 OCR 模型。

        在实例刚启动截图时，后台线程预先加载 cnocr 等 OCR 依赖。
        截图是 I/O 密集型，导入是 CPU 密集型，两者并行可加速启动 0.5~5 秒。
        """
        return

    @cached_class_property
    def worker(self):
        """
        后台线程池，用于执行非阻塞的后台任务。

        Examples:
            >>> def func(image):
            ...     with self.config.multi_set():
            ...         self.dungeon_get_simuni_point(image)
            ...         self.dungeon_update_stamina(image)
            >>> ModuleBase.worker.submit(func, self.device.image)
        """
        logger.hr('Creating worker')
        from concurrent.futures import ThreadPoolExecutor
        pool = ThreadPoolExecutor(1)
        return pool

    def ensure_button(self, button):
        if isinstance(button, str):
            button = HierarchyButton(self.device.hierarchy, button)

        return button

    def loop(self, skip_first=True, timeout=None):
        """
        状态循环的语法糖，每次迭代自动截图。

        Args:
            skip_first: 为 True 时复用上一次截图，避免冗余捕获。
            timeout: 超时秒数或 Timer 对象，超时后自动退出循环。

        Yields:
            np.ndarray: 当前截图。

        Examples:
            基本状态循环：
            >>> for _ in self.loop():
            ...     if self.appear(END_CONDITION):
            ...         break
            ...     if self.appear_then_click(BUTTON_A):
            ...         continue

            带超时的状态循环：
            >>> for _ in self.loop(timeout=2):
            ...     if self.appear(END_CONDITION):
            ...         break
            >>> else:
            ...     logger.warning('等待超时')
        """
        if timeout is not None:
            if isinstance(timeout, Timer):
                timeout.reset()
            else:
                timeout = Timer.from_seconds(timeout).start()

        while 1:
            if timeout is not None:
                if timeout.reached():
                    return

            if skip_first:
                skip_first = False
            else:
                self.device.screenshot()

            try:
                yield self.device.image
            except AttributeError:
                self.device.screenshot()
                yield self.device.image

    def loop_hierarchy(self, skip_first=True):
        """
        层级结构状态循环的语法糖，每次迭代自动获取 UI 层级树。

        Args:
            skip_first: 为 True 时复用上一次层级数据。

        Yields:
            etree._Element: 当前 UI 层级树。
        """
        while 1:
            if skip_first:
                skip_first = False
            else:
                self.device.dump_hierarchy()
            yield self.device.hierarchy

    def loop_screenshot_hierarchy(self, skip_first=True):
        """
        同时获取截图和层级树的状态循环语法糖。

        Args:
            skip_first: 为 True 时复用上一次截图和层级数据。

        Yields:
            tuple[np.ndarray, etree._Element]: (截图, UI层级树)。
        """
        while 1:
            if skip_first:
                skip_first = False
            else:
                self.device.screenshot()
                self.device.dump_hierarchy()
            yield self.device.image, self.device.hierarchy

    def appear(self, button, offset: Union[bool, int, Tuple[int, int]] = 0, interval=0, similarity=0.85, threshold=10):
        """
        检测按钮/模板/层级元素是否出现在当前截图上。

        支持三种检测模式：
        - 颜色检测（默认）：通过区域平均颜色判断
        - 模板匹配（offset 非零）：通过图像模板匹配判断
        - 层级检测（HierarchyButton）：通过 xpath 查找 UI 层级树

        Args:
            button: 待检测的 Button、Template、HierarchyButton 或 xpath 字符串。
            offset: 启用模板匹配的偏移量。
                False/0 表示使用颜色检测，True 使用默认偏移，int/tuple 指定偏移范围。
            interval: 两次检测之间的最小间隔秒数，防止快速重复触发。
            similarity: 模板匹配相似度阈值，0~1。
            threshold: 颜色检测容差，0~255，值越小要求越严格。

        Returns:
            bool: 元素是否出现。
        """
        button = self.ensure_button(button)
        self.device.stuck_record_add(button)

        if interval:
            if button.name in self.interval_timer:
                if self.interval_timer[button.name].limit != interval:
                    self.interval_timer[button.name] = Timer(interval)
            else:
                self.interval_timer[button.name] = Timer(interval)
            if not self.interval_timer[button.name].reached():
                return False

        if isinstance(button, HierarchyButton):
            appear = bool(button)
        elif offset:
            if isinstance(offset, bool):
                offset = self.config.BUTTON_OFFSET
            appear = button.match(self.device.image, offset=offset, similarity=similarity)
        else:
            appear = button.appear_on(self.device.image, threshold=threshold)

        if appear and interval:
            self.interval_timer[button.name].reset()

        return appear

    def match_template_color(self, button, offset=(20, 20), interval=0, similarity=0.85, threshold=30):
        """
        同时使用模板匹配和颜色检测来判断按钮是否出现。

        与 `appear()` 不同，此方法要求模板匹配和颜色检测同时通过。

        Args:
            button: 待检测的 Button 实例。
            offset: 模板匹配的偏移范围。
            interval: 两次检测之间的最小间隔秒数。
            similarity: 模板匹配相似度阈值，0~1。
            threshold: 颜色检测容差，0~255。

        Returns:
            bool: 按钮是否出现。
        """
        button = self.ensure_button(button)
        self.device.stuck_record_add(button)

        if interval:
            if button.name in self.interval_timer:
                if self.interval_timer[button.name].limit != interval:
                    self.interval_timer[button.name] = Timer(interval)
            else:
                self.interval_timer[button.name] = Timer(interval)
            if not self.interval_timer[button.name].reached():
                return False

        appear = button.match_template_color(
            self.device.image, offset=offset, similarity=similarity, threshold=threshold)

        if appear and interval:
            self.interval_timer[button.name].reset()

        return appear

    def appear_then_click(self, button, screenshot=False, genre='items',
                          offset: Union[bool, int, Tuple[int, int]] = 0, interval=0, similarity=0.85,
                          threshold=30):
        button = self.ensure_button(button)
        appear = self.appear(button, offset=offset, interval=interval, similarity=similarity, threshold=threshold)
        if appear:
            if screenshot:
                self.device.sleep(self.config.WAIT_BEFORE_SAVING_SCREEN_SHOT)
                self.device.screenshot()
                self.device.save_screenshot(genre=genre)
            self.device.sleep(0.1)  # 因为点击太快被多退役了一艘联动金船惨案QAQ
            self.device.click(button)
        return appear

    def wait_until_appear(self, button, offset=0, skip_first_screenshot=False):
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.appear(button, offset=offset):
                break

    def wait_until_appear_then_click(self, button, offset=0):
        self.wait_until_appear(button, offset=offset)
        self.device.click(button)

    def wait_until_disappear(self, button, offset=0):
        while 1:
            self.device.screenshot()
            if not self.appear(button, offset=offset):
                break

    def wait_until_stable(self, button, timer=Timer(0.3, count=1), timeout=Timer(5, count=10), skip_first_screenshot=True):
        button._match_init = False
        timeout.reset()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if button._match_init:
                if button.match(self.device.image, offset=(0, 0)):
                    if timer.reached():
                        break
                else:
                    button.load_color(self.device.image)
                    timer.reset()
            else:
                button.load_color(self.device.image)
                button._match_init = True

            if timeout.reached():
                logger.warning(f'wait_until_stable({button}) timeout')
                break

    def image_crop(self, button, copy=True):
        """
        从当前截图中裁剪指定区域。

        Args:
            button: Button 实例或区域元组 (x1, y1, x2, y2)。
            copy: 是否复制裁剪结果，False 时返回原图视图以节省内存。

        Returns:
            np.ndarray: 裁剪后的图像。
        """
        if isinstance(button, Button):
            return crop(self.device.image, button.area, copy=copy)
        elif hasattr(button, 'area'):
            return crop(self.device.image, button.area, copy=copy)
        else:
            return crop(self.device.image, button, copy=copy)

    def image_color_count(self, button, color, threshold=221, count=50):
        """
        统计指定区域中接近目标颜色的像素数量，判断是否达标。

        Args:
            button: Button 实例、区域元组或 np.ndarray 图像。
            color: 目标 RGB 颜色值。
            threshold: 颜色相似度容差，255 表示完全相同，值越小要求越严格。
            count: 像素数量阈值，超过此数返回 True。

        Returns:
            bool: 匹配像素数是否超过阈值。
        """
        if isinstance(button, np.ndarray):
            image = button
        else:
            image = self.image_crop(button, copy=False)
        return image_color_count(image, color, threshold, count)

    def image_color_button(self, area, color, color_threshold=250, encourage=5, name='COLOR_BUTTON'):
        """
        在指定区域中查找纯色区域，将其转换为可点击的 Button。

        Args:
            area: 搜索区域 (x1, y1, x2, y2)。
            color: 目标 RGB 颜色值。
            color_threshold: 颜色匹配容差，0~255，255 表示精确匹配。
            encourage: 生成按钮的半径。
            name: 按钮名称。

        Returns:
            Button: 匹配成功返回 Button 实例，否则返回 None。
        """
        image = color_similarity_2d(self.image_crop(area, copy=False), color=color)
        points = np.array(np.where(image > color_threshold)).T[:, ::-1]
        if points.shape[0] < encourage ** 2:
            # 匹配像素不足，无法生成有效按钮
            return None

        point = fit_points(points, mod=image_size(image), encourage=encourage)
        point = ensure_int(point + area[:2])
        button_area = area_offset((-encourage, -encourage, encourage, encourage), offset=point)
        color = get_color(self.device.image, button_area)
        return Button(area=button_area, color=color, button=button_area, name=name)

    def get_interval_timer(self, button, interval=5, renew=False) -> Timer:
        if hasattr(button, 'name'):
            name = button.name
        elif callable(button):
            name = button.__name__
        else:
            name = str(button)

        try:
            timer = self.interval_timer[name]
            if renew and timer.limit != interval:
                timer = Timer(interval)
                self.interval_timer[name] = timer
            return timer
        except KeyError:
            timer = Timer(interval)
            self.interval_timer[name] = timer
            return timer

    def interval_reset(self, button, interval=3):
        if isinstance(button, (list, tuple)):
            for b in button:
                self.interval_reset(b)
            return

        if button is not None:
            if button.name in self.interval_timer:
                self.interval_timer[button.name].reset()
            else:
                self.interval_timer[button.name] = Timer(interval).reset()

    def interval_clear(self, button, interval=3):
        if isinstance(button, (list, tuple)):
            for b in button:
                self.interval_clear(b)
            return

        if button is not None:
            if button.name in self.interval_timer:
                self.interval_timer[button.name].clear()
            else:
                self.interval_timer[button.name] = Timer(interval).clear()

    _image_file = ''

    @property
    def image_file(self):
        return self._image_file

    @image_file.setter
    def image_file(self, value):
        """
        从本地文件加载测试图像，用于开发调试。

        将图片加载到 self.device.image，无需连接模拟器即可测试图像识别逻辑。
        """
        if isinstance(value, Image.Image):
            value = np.array(value)
        elif isinstance(value, str):
            value = load_image(value)

        width, height = image_size(value)
        set_template_match_non_native_720p(width != 1280 or height != 720, resolution=(width, height))
        self.device.image = value

    def set_server(self, server):
        """
        切换游戏服务器，全局生效（仅用于开发调试）。

        切换后影响资源文件路径和服务器特定方法的分发。
        """
        package = to_package(server)
        self.device.package = package
        set_server(server)
        logger.attr('Server', self.config.SERVER)
