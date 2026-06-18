import numpy as np
from scipy import signal

from module.base.base import ModuleBase
from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import color_similarity_2d, random_rectangle_point, rgb2gray
from module.logger import logger


class Scroll:
    color_threshold = 221
    drag_threshold = 0.05
    edge_threshold = 0.05
    edge_add = (0.3, 0.5)

    def __init__(self, area, color, is_vertical=True, name='Scroll'):
        """
        Args:
            area (Button, tuple): 滚动条整体的按钮或区域。
            color (tuple): 滚动条的 RGB 颜色。
            is_vertical (bool): True 为垂直滚动条，False 为水平滚动条。
            name (str): 滚动条名称。
        """
        if isinstance(area, Button):
            name = area.name
            area = area.area
        self.area = area
        self.color = color
        self.is_vertical = is_vertical
        self.name = name

        if self.is_vertical:
            self.total = self.area[3] - self.area[1]
        else:
            self.total = self.area[2] - self.area[0]
        # 默认值，会在 match_color() 中更新
        self.length = self.total / 2
        self.drag_interval = Timer(1, count=2)
        self.drag_timeout = Timer(5, count=10)

    def match_color(self, main):
        """
        通过颜色匹配识别滚动条位置，返回掩码数组。

        Args:
            main (ModuleBase): 模块基类实例。

        Returns:
            np.ndarray: 形状 (n,)，dtype bool，标记滚动条所在的行列。
        """
        image = main.image_crop(self.area, copy=False)
        image = color_similarity_2d(image, color=self.color)
        mask = np.max(image, axis=1 if self.is_vertical else 0) > self.color_threshold
        self.length = np.sum(mask)
        return mask

    def cal_position(self, main):
        """
        计算滚动条当前位置。

        Args:
            main (ModuleBase): 模块基类实例。

        Returns:
            float: 位置值，0 到 1 之间。
        """
        mask = self.match_color(main)
        middle = np.mean(np.where(mask)[0])

        position = (middle - self.length / 2) / (self.total - self.length)
        position = position if position > 0 else 0.0
        position = position if position < 1 else 1.0
        logger.attr(self.name, f'{position:.2f} ({middle}-{self.length / 2})/({self.total}-{self.length})')
        return position

    def position_to_screen(self, position, random_range=(-0.05, 0.05)):
        """
        将滚动条位置转换为屏幕坐标。调用前需先调用 cal_position() 或 match_color() 获取 length。

        Args:
            position (int, float): 滚动条位置，0 到 1 之间。
            random_range (tuple): 随机偏移范围。

        Returns:
            tuple[int]: (左上角 x, 左上角 y, 右下角 x, 右下角 y)。
        """
        position = np.add(position, random_range)
        middle = position * (self.total - self.length) + self.length / 2
        middle = middle.astype(int)
        if self.is_vertical:
            middle += self.area[1]
            while np.max(middle) >= 720:
                middle -= 2
            while np.min(middle) <= 0:
                middle += 2
            area = (self.area[0], middle[0], self.area[2], middle[1])
        else:
            middle += self.area[0]
            while np.max(middle) >= 1280:
                middle -= 2
            while np.min(middle) <= 0:
                middle += 2
            area = (middle[0], self.area[1], middle[1], self.area[3])
        return area

    def appear(self, main):
        """
        检测滚动条是否出现在屏幕上。

        Args:
            main (ModuleBase): 模块基类实例。

        Returns:
            bool: 是否出现。
        """
        return np.mean(self.match_color(main)) > 0.1

    def at_top(self, main):
        return self.cal_position(main) < self.edge_threshold

    def at_bottom(self, main):
        return self.cal_position(main) > 1 - self.edge_threshold

    def set(self, position, main, random_range=(-0.05, 0.05), distance_check=True, skip_first_screenshot=True):
        """
        设置滚动条到指定位置。

        Args:
            position (float, int): 目标位置，0 到 1 之间。
            main (ModuleBase): 模块基类实例。
            random_range (tuple(int, float)): 随机偏移范围。
            distance_check (bool): 是否跳过过短的滑动。
            skip_first_screenshot: 是否跳过首次截图。

        Returns:
            bool: 是否执行了拖拽操作。
        """
        logger.info(f'{self.name} set to {position}')
        self.drag_interval.clear()
        self.drag_timeout.reset()
        dragged = 0
        if position <= self.edge_threshold:
            random_range = np.subtract(0, self.edge_add)
        if position >= 1 - self.edge_threshold:
            random_range = self.edge_add

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            current = self.cal_position(main)
            if abs(position - current) < self.drag_threshold:
                break
            if self.length:
                self.drag_timeout.reset()
            else:
                if self.drag_timeout.reached():
                    logger.warning('滚动条消失，假定已设置完成')
                    break
                else:
                    continue

            if self.drag_interval.reached():
                p1 = random_rectangle_point(self.position_to_screen(current), n=1)
                p2 = random_rectangle_point(self.position_to_screen(position, random_range=random_range), n=1)
                main.device.swipe(p1, p2, name=self.name, distance_check=distance_check)
                self.drag_interval.reset()
                dragged += 1

        return dragged

    def set_top(self, main, random_range=(-0.05, 0.05), skip_first_screenshot=True):
        return self.set(0.00, main=main, random_range=random_range, skip_first_screenshot=skip_first_screenshot)

    def set_bottom(self, main, random_range=(-0.05, 0.05), skip_first_screenshot=True):
        return self.set(1.00, main=main, random_range=random_range, skip_first_screenshot=skip_first_screenshot)

    def drag_page(self, page, main, random_range=(-0.05, 0.05), skip_first_screenshot=True):
        """
        向前或向后拖拽滚动条翻页。

        Args:
            page (int, float): 相对拖拽量。1.0 表示下一页，-1.0 表示上一页。
            main (ModuleBase): 模块基类实例。
            random_range (tuple[float]): 随机偏移范围。
            skip_first_screenshot: 是否跳过首次截图。
        """
        if not skip_first_screenshot:
            main.device.screenshot()
        current = self.cal_position(main)

        multiply = self.length / (self.total - self.length)
        target = current + page * multiply
        target = round(min(max(target, 0), 1), 3)
        return self.set(target, main=main, random_range=random_range, skip_first_screenshot=True)

    def next_page(self, main, page=0.8, random_range=(-0.01, 0.01), skip_first_screenshot=True):
        return self.drag_page(page, main=main, random_range=random_range, skip_first_screenshot=skip_first_screenshot)

    def prev_page(self, main, page=0.8, random_range=(-0.01, 0.01), skip_first_screenshot=True):
        return self.drag_page(-page, main=main, random_range=random_range, skip_first_screenshot=skip_first_screenshot)


class AdaptiveScroll(Scroll):
    def __init__(self, area, parameters: dict = None, background=5, is_vertical=True, name='Scroll'):
        """
        自适应滚动条，通过峰值检测自动识别滚动条位置。

        Args:
            area (Button, tuple): 滚动条整体的按钮或区域。
            parameters (dict): 传递给 scipy.find_peaks 的参数。
            background (int): 背景扩展像素数。
            is_vertical (bool): True 为垂直滚动条，False 为水平滚动条。
            name (str): 滚动条名称。
        """
        if parameters is None:
            parameters = {}
        self.parameters = parameters
        self.background = background
        super().__init__(area, color=(255, 255, 255), is_vertical=is_vertical, name=name)

    def match_color(self, main):
        if self.is_vertical:
            area = (self.area[0] - self.background, self.area[1], self.area[2] + self.background, self.area[3])
            image = main.image_crop(area, copy=False)
            image = rgb2gray(image)
            image = image.flatten()
            wlen = area[2] - area[0]
        else:
            area = (self.area[0], self.area[1] - self.background, self.area[2], self.area[3] + self.background)
            image = main.image_crop(area, copy=False)
            image = rgb2gray(image)
            image = image.flatten('F')
            wlen = area[3] - area[1]

        parameters = {
            'height': 128,
            'prominence': 30,
            'wlen': wlen,
            'width': 2,
        }
        parameters.update(self.parameters)
        peaks, _ = signal.find_peaks(image, **parameters)
        peaks //= wlen

        self.length = len(peaks)
        mask = np.zeros((self.total,), dtype=np.bool_)
        mask[peaks] = 1
        return mask
