# 此文件定义了 Alas 视觉交互系统的核心基类：Button（按钮）及相关网格。
# 它是所有 UI 交互的基本单位，包含了坐标偏移、颜色/模板识别逻辑以及模拟点击的具体实现方案。
import typing as t
import os
import traceback

from PIL import ImageDraw

from module.base.decorator import cached_property
from module.base.resource import Resource
from module.base.utils import *
from module.config.server import VALID_SERVER
from module.logger import logger


class Button(Resource):
    def __init__(self, area, color, button, file=None, name=None):
        """初始化 Button 实例。

        Args:
            area (dict[tuple], tuple): 按钮在截图中出现的区域。
                (左上角 x, 左上角 y, 右下角 x, 右下角 y)
            color (dict[tuple], tuple): 期望该区域呈现的颜色。
                (r, g, b)
            button (dict[tuple], tuple): 按钮出现时的可点击区域。
                (左上角 x, 左上角 y, 右下角 x, 右下角 y)
                若传入空元组，则此对象仅作为检测器使用。

        Examples:
            BATTLE_PREPARATION = Button(
                area=(1562, 908, 1864, 1003),
                color=(231, 181, 90),
                button=(1562, 908, 1864, 1003)
            )
        """
        self.raw_area = area
        self.raw_color = color
        self.raw_button = button
        self.raw_file = file
        self.raw_name = name

        self._button_offset = None
        self._match_init = False
        self._match_binary_init = False
        self._match_luma_init = False
        self.image = None
        self.image_binary = None
        self.image_luma = None

        if self.file:
            self.resource_add(key=self.file)

    cached = ['area', 'color', '_button', 'file', 'name', 'is_gif']

    @cached_property
    def area(self):
        return self.parse_property(self.raw_area)

    @cached_property
    def color(self):
        return self.parse_property(self.raw_color)

    @cached_property
    def _button(self):
        return self.parse_property(self.raw_button)

    @cached_property
    def file(self):
        return self.parse_property(self.raw_file)

    @cached_property
    def name(self):
        if self.raw_name:
            return self.raw_name
        elif self.file:
            return os.path.splitext(os.path.split(self.file)[1])[0]
        else:
            return 'BUTTON'

    @cached_property
    def is_gif(self):
        if self.file:
            return os.path.splitext(self.file)[1] == '.gif'
        else:
            return False

    def __str__(self):
        return self.name

    __repr__ = __str__

    def __eq__(self, other):
        return str(self) == str(other)

    def __hash__(self):
        return hash(self.name)

    def __bool__(self):
        return True

    @property
    def button(self):
        if self._button_offset is None:
            return self._button
        else:
            return self._button_offset

    def appear_on(self, image, threshold=10):
        """检测按钮是否出现在截图上。

        Args:
            image (np.ndarray): 截图。
            threshold (int): 颜色相似度阈值，默认为 10。

        Returns:
            bool: 若按钮出现在截图上则返回 True。
        """
        return color_similar(
            color1=get_color(image, self.area),
            color2=self.color,
            threshold=threshold
        )

    def load_color(self, image):
        """从指定截图的对应区域加载颜色。此方法不可逆，仅在特殊场景下使用。

        Args:
            image: 截图。

        Returns:
            tuple: 颜色值 (r, g, b)。
        """
        self.__dict__['color'] = get_color(image, self.area)
        self.image = crop(image, self.area)
        self.__dict__['is_gif'] = False
        return self.color

    def load_offset(self, button):
        """从另一个按钮加载偏移量。

        Args:
            button (Button): 参考按钮。
        """
        offset = np.subtract(button.button, button._button)[:2]
        self._button_offset = area_offset(self._button, offset=offset)

    def clear_offset(self):
        self._button_offset = None

    def ensure_template(self):
        """加载资源图像。若需调用 self.match，应先调用此方法。"""
        if not self._match_init:
            if self.is_gif:
                self.image = []
                import imageio
                for image in imageio.mimread(self.file):
                    image = image[:, :, :3].copy() if len(image.shape) == 3 else image
                    image = crop(image, self.area)
                    self.image.append(image)
            else:
                self.image = load_image(self.file, self.area)
            self._match_init = True

    def ensure_binary_template(self):
        """加载二值化资源图像。若需调用 self.match_binary，应先调用此方法。"""
        if not self._match_binary_init:
            if self.is_gif:
                self.image_binary = []
                for image in self.image:
                    image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                    _, image_binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
                    self.image_binary.append(image_binary)
            else:
                image_gray = cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY)
                _, self.image_binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
            self._match_binary_init = True

    def ensure_luma_template(self):
        if not self._match_luma_init:
            if self.is_gif:
                self.image_luma = []
                for image in self.image:
                    luma = rgb2luma(image)
                    self.image_luma.append(luma)
            else:
                self.image_luma = rgb2luma(self.image)
            self._match_luma_init = True

    def resource_release(self):
        super().resource_release()
        self.image = None
        self.image_binary = None
        self.image_luma = None
        self._match_init = False
        self._match_binary_init = False
        self._match_luma_init = False

    def match(self, image, offset=30, similarity=0.85):
        """通过模板匹配检测按钮。部分按钮的位置可能不固定。

        Args:
            image: 截图。
            offset (int, tuple): 检测区域偏移量。
            similarity (float): 相似度阈值，范围 0-1。

        Returns:
            bool: 匹配成功返回 True。
        """
        similarity = lower_template_match_similarity(similarity)
        self.ensure_template()

        if isinstance(offset, tuple):
            if len(offset) == 2:
                offset = np.array((-offset[0], -offset[1], offset[0], offset[1]))
            else:
                offset = np.array(offset)
        else:
            offset = np.array((-3, -offset, 3, offset))
        image = crop(image, offset + self.area, copy=False)

        if self.is_gif:
            for template in self.image:
                res = cv2.matchTemplate(template, image, cv2.TM_CCOEFF_NORMED)
                _, sim, _, point = cv2.minMaxLoc(res)
                self._button_offset = area_offset(self._button, offset[:2] + np.array(point))
                if sim > similarity:
                    return True
            return False
        else:
            res = cv2.matchTemplate(self.image, image, cv2.TM_CCOEFF_NORMED)
            _, sim, _, point = cv2.minMaxLoc(res)
            self._button_offset = area_offset(self._button, offset[:2] + np.array(point))
            return sim > similarity

    def match_binary(self, image, offset=30, similarity=0.85):
        """通过二值化模板匹配检测按钮。部分按钮的位置可能不固定。

        Args:
            image: 截图。
            offset (int, tuple): 检测区域偏移量。
            similarity (float): 相似度阈值，范围 0-1。

        Returns:
            bool: 匹配成功返回 True。
        """
        similarity = lower_template_match_similarity(similarity)
        self.ensure_template()
        self.ensure_binary_template()

        if isinstance(offset, tuple):
            if len(offset) == 2:
                offset = np.array((-offset[0], -offset[1], offset[0], offset[1]))
            else:
                offset = np.array(offset)
        else:
            offset = np.array((-3, -offset, 3, offset))
        image = crop(image, offset + self.area, copy=False)

        if self.is_gif:
            for template in self.image_binary:
                # 灰度化
                image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                # 二值化
                _, image_binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
                # 模板匹配
                res = cv2.matchTemplate(template, image_binary, cv2.TM_CCOEFF_NORMED)
                _, sim, _, point = cv2.minMaxLoc(res)
                self._button_offset = area_offset(self._button, offset[:2] + np.array(point))
                if sim > similarity:
                    return True
            return False
        else:
            # 灰度化
            image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            # 二值化
            _, image_binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
            # 模板匹配
            res = cv2.matchTemplate(self.image_binary, image_binary, cv2.TM_CCOEFF_NORMED)
            _, sim, _, point = cv2.minMaxLoc(res)
            self._button_offset = area_offset(self._button, offset[:2] + np.array(point))
            return sim > similarity

    def match_luma(self, image, offset=30, similarity=0.85):
        """通过 Y 通道（亮度）模板匹配检测按钮。

        Args:
            image: 截图。
            offset (int, tuple): 检测区域偏移量。
            similarity (float): 相似度阈值，范围 0-1。

        Returns:
            bool: 匹配成功返回 True。
        """
        similarity = lower_template_match_similarity(similarity)
        self.ensure_template()
        self.ensure_luma_template()

        if isinstance(offset, tuple):
            if len(offset) == 2:
                offset = np.array((-offset[0], -offset[1], offset[0], offset[1]))
            else:
                offset = np.array(offset)
        else:
            offset = np.array((-3, -offset, 3, offset))
        image = crop(image, offset + self.area, copy=False)

        if self.is_gif:
            image_luma = rgb2luma(image)
            for template in self.image_luma:
                res = cv2.matchTemplate(template, image_luma, cv2.TM_CCOEFF_NORMED)
                _, sim, _, point = cv2.minMaxLoc(res)
                self._button_offset = area_offset(self._button, offset[:2] + np.array(point))
                if sim > similarity:
                    return True
        else:
            image_luma = rgb2luma(image)
            res = cv2.matchTemplate(self.image_luma, image_luma, cv2.TM_CCOEFF_NORMED)
            _, sim, _, point = cv2.minMaxLoc(res)
            self._button_offset = area_offset(self._button, offset[:2] + np.array(point))
            return sim > similarity

    def match_template_color(self, image, offset=(20, 20), similarity=0.85, threshold=30):
        """先进行模板匹配，再进行颜色匹配。

        Args:
            image: 截图。
            offset (int, tuple): 检测区域偏移量。
            similarity (float): 模板匹配相似度阈值，范围 0-1。
            threshold (int): 颜色相似度阈值，默认为 30。

        Returns:
            bool: 匹配成功返回 True。
        """
        if self.match_luma(image, offset=offset, similarity=similarity):
            diff = np.subtract(self.button, self._button)[:2]
            area = area_offset(self.area, offset=diff)
            color = get_color(image, area)
            return color_similar(color1=color, color2=self.color, threshold=threshold)
        else:
            return False

    def crop(self, area, image=None, name=None):
        """根据相对坐标获取新的按钮。

        Args:
            area (tuple): 相对于当前按钮的裁剪区域。
            image (np.ndarray): 截图。若提供，则从中加载颜色和图像。
            name (str): 新按钮的名称。

        Returns:
            Button: 裁剪后的新按钮。
        """
        if name is None:
            name = self.name
        new_area = area_offset(area, offset=self.area[:2])
        new_button = area_offset(area, offset=self.button[:2])
        button = Button(area=new_area, color=self.color, button=new_button, file=self.file, name=name)
        if image is not None:
            button.load_color(image)
        return button

    def move(self, vector, image=None, name=None):
        """移动按钮位置。

        Args:
            vector (tuple): 移动向量。
            image (np.ndarray): 截图。若提供，则从中加载颜色和图像。
            name (str): 新按钮的名称。

        Returns:
            Button: 移动后的新按钮。
        """
        if name is None:
            name = self.name
        new_area = area_offset(self.area, offset=vector)
        new_button = area_offset(self.button, offset=vector)
        button = Button(area=new_area, color=self.color, button=new_button, file=self.file, name=name)
        if image is not None:
            button.load_color(image)
        return button

    def split_server(self):
        """拆分为 4 个服务器专用按钮。

        Returns:
            dict[str, Button]: 以服务器名称为键、对应按钮为值的字典。
        """
        out = {}
        for s in VALID_SERVER:
            out[s] = Button(
                area=self.parse_property(self.raw_area, s),
                color=self.parse_property(self.raw_color, s),
                button=self.parse_property(self.raw_button, s),
                file=self.parse_property(self.raw_file, s),
                name=self.name
            )
        return out


class ButtonGrid:
    def __init__(self, origin, delta, button_shape, grid_shape, name=None):
        self.origin = np.array(origin)
        self.delta = np.array(delta)
        self.button_shape = np.array(button_shape)
        self.grid_shape = np.array(grid_shape)
        if name:
            self._name = name
        else:
            (filename, line_number, function_name, text) = traceback.extract_stack()[-2]
            self._name = text[:text.find('=')].strip()

    def __getitem__(self, item):
        base = np.round(np.array(item) * self.delta + self.origin).astype(int)
        area = tuple(np.append(base, base + self.button_shape))
        return Button(area=area, color=(), button=area, name='%s_%s_%s' % (self._name, item[0], item[1]))

    def generate(self):
        for y in range(self.grid_shape[1]):
            for x in range(self.grid_shape[0]):
                yield x, y, self[x, y]

    @cached_property
    def buttons(self):
        return list([button for _, _, button in self.generate()])

    def crop(self, area, name=None):
        """根据相对坐标裁剪 ButtonGrid。

        Args:
            area (tuple): 相对于 self.origin 的裁剪区域。
            name (str): 新 ButtonGrid 实例的名称。

        Returns:
            ButtonGrid: 裁剪后的新 ButtonGrid 实例。
        """
        if name is None:
            name = self._name
        origin = self.origin + area[:2]
        button_shape = np.subtract(area[2:], area[:2])
        return ButtonGrid(
            origin=origin, delta=self.delta, button_shape=button_shape, grid_shape=self.grid_shape, name=name)

    def move(self, vector, name=None):
        """移动 ButtonGrid 位置。

        Args:
            vector (tuple): 移动向量。
            name (str): 新 ButtonGrid 实例的名称。

        Returns:
            ButtonGrid: 移动后的新 ButtonGrid 实例。
        """
        if name is None:
            name = self._name
        origin = self.origin + vector
        return ButtonGrid(
            origin=origin, delta=self.delta, button_shape=self.button_shape, grid_shape=self.grid_shape, name=name)

    def gen_mask(self):
        """生成遮罩图像，用于调试显示此 ButtonGrid 对象。

        Returns:
            PIL.Image.Image: 区域为白色、背景为黑色的遮罩图像。
        """
        image = Image.new("RGB", (1280, 720), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        for button in self.buttons:
            draw.rectangle((button.area[:2], button.button[2:]), fill=(255, 255, 255), outline=None)
        return image

    def show_mask(self):
        self.gen_mask().show()

    def save_mask(self):
        """将遮罩图像保存为 {name}.png。"""
        self.gen_mask().save(f'{self._name}.png')
