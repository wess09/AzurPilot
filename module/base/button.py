"""按钮与网格组件模块。

定义视觉交互系统的核心基类 Button 及 ButtonGrid，是所有 UI 交互的基本单位。
包含坐标偏移、颜色/模板识别逻辑以及模拟点击的具体实现方案。
"""

# 此文件定义了 Alas 视觉交互系统的核心基类：Button（按钮）及相关网格。
# 它是所有 UI 交互的基本单位，包含了坐标偏移、颜色/模板识别逻辑以及模拟点击的具体实现方案。
import typing as t
import os
import traceback
from threading import RLock

from PIL import ImageDraw

from module.base.decorator import cached_property
from module.base.resource import Resource
from module.base.runtime_context import clear_runtime_state, get_runtime_context, runtime_state
from module.base.utils import *
from module.config.server import VALID_SERVER
from module.logger import logger


_UNSET = object()


class _ButtonRuntimeState:
    """Button 在单个 worker 中的写时覆盖状态。

    静态模板图像始终放在 Button 自身的共享缓存中。只有 ``load_color()`` 或外部
    直接改写匹配字段时，才会在这里保存截图模板/颜色的局部引用，不深拷贝图像。
    """

    __slots__ = (
        'area',
        'button',
        'name',
        'button_offset',
        'color',
        'is_gif',
        'image',
        'image_binary',
        'image_luma',
        'match_init',
        'match_binary_init',
        'match_luma_init',
        'template_override',
    )

    def __init__(self):
        self.area = _UNSET
        self.button = _UNSET
        self.name = _UNSET
        self.button_offset = None
        self.color = _UNSET
        self.is_gif = _UNSET
        self.image = _UNSET
        self.image_binary = _UNSET
        self.image_luma = _UNSET
        self.match_init = _UNSET
        self.match_binary_init = _UNSET
        self.match_luma_init = _UNSET
        self.template_override = False


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

        # 共享字段只保存静态资源缓存。运行中的可变覆盖进入 RuntimeContext，
        # 使不同 worker 共享模板数组而不共享动态颜色、截图模板和偏移坐标。
        self.__dict__['_shared_button_offset'] = None
        self.__dict__['_shared_area'] = _UNSET
        self.__dict__['_shared_button'] = _UNSET
        self.__dict__['_shared_name'] = _UNSET
        self.__dict__['_shared_color'] = _UNSET
        self.__dict__['_shared_is_gif'] = _UNSET
        self.__dict__['_shared_match_init'] = False
        self.__dict__['_shared_match_binary_init'] = False
        self.__dict__['_shared_match_luma_init'] = False
        self.__dict__['_shared_image'] = None
        self.__dict__['_shared_image_binary'] = None
        self.__dict__['_shared_image_luma'] = None
        self.__dict__['_template_lock'] = RLock()

        if self.file:
            self.resource_add(key=self.file)

    cached = ['area', '_button', 'file', 'name']

    @property
    def area(self):
        value = self._get_runtime_value('area')
        if value is _UNSET:
            value = self.parse_property(self.raw_area)
            self.__dict__['_shared_area'] = value
        return value

    @area.setter
    def area(self, value):
        self._set_runtime_value('area', value, template_override=True)

    @property
    def color(self):
        value = self._get_runtime_value('color')
        if value is _UNSET:
            value = self.parse_property(self.raw_color)
            self.__dict__['_shared_color'] = value
        return value

    @color.setter
    def color(self, value):
        # 颜色阈值与模板图像相互独立，单独改写颜色不应复制共享模板。
        self._set_runtime_value('color', value)

    @property
    def _button(self):
        value = self._get_runtime_value('button')
        if value is _UNSET:
            value = self.parse_property(self.raw_button)
            self.__dict__['_shared_button'] = value
        return value

    @_button.setter
    def _button(self, value):
        # 点击区域变化不影响识别模板，不能因此为当前 worker 复制模板图像。
        self._set_runtime_value('button', value)

    @cached_property
    def file(self):
        return self.parse_property(self.raw_file)

    @property
    def name(self):
        value = self._get_runtime_value('name')
        if value is _UNSET:
            if self.raw_name:
                value = self.raw_name
            elif self.file:
                value = os.path.splitext(os.path.split(self.file)[1])[0]
            else:
                value = 'BUTTON'
            self.__dict__['_shared_name'] = value
        return value

    @name.setter
    def name(self, value):
        # 名称只用于日志/哈希；临时改名不应触发模板重载。
        self._set_runtime_value('name', value)

    @property
    def is_gif(self):
        value = self._get_runtime_value('is_gif')
        if value is _UNSET:
            value = bool(self.file and os.path.splitext(self.file)[1] == '.gif')
            self.__dict__['_shared_is_gif'] = value
        return value

    @is_gif.setter
    def is_gif(self, value):
        self._set_runtime_value('is_gif', value, template_override=True)

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

    def _state(self) -> _ButtonRuntimeState | None:
        return runtime_state(self, 'button', _ButtonRuntimeState)

    def _get_runtime_value(self, field):
        state = self._state()
        if state is not None:
            value = getattr(state, field)
            if value is not _UNSET:
                return value
        return self.__dict__[f'_shared_{field}']

    def _set_runtime_value(self, field, value, template_override=False):
        state = self._state()
        if state is None:
            self.__dict__[f'_shared_{field}'] = value
            return
        setattr(state, field, value)
        if template_override:
            state.template_override = True

    def _set_shared_value(self, field, value):
        self.__dict__[f'_shared_{field}'] = value

    @property
    def _button_offset(self):
        state = self._state()
        return state.button_offset if state is not None else self.__dict__['_shared_button_offset']

    @_button_offset.setter
    def _button_offset(self, value):
        state = self._state()
        if state is None:
            self.__dict__['_shared_button_offset'] = value
        else:
            state.button_offset = value

    @property
    def image(self):
        return self._get_runtime_value('image')

    @image.setter
    def image(self, value):
        self._set_runtime_value('image', value, template_override=True)

    @property
    def image_binary(self):
        return self._get_runtime_value('image_binary')

    @image_binary.setter
    def image_binary(self, value):
        self._set_runtime_value('image_binary', value, template_override=True)

    @property
    def image_luma(self):
        return self._get_runtime_value('image_luma')

    @image_luma.setter
    def image_luma(self, value):
        self._set_runtime_value('image_luma', value, template_override=True)

    @property
    def _match_init(self):
        return self._get_runtime_value('match_init')

    @_match_init.setter
    def _match_init(self, value):
        self._set_runtime_value('match_init', value, template_override=True)

    @property
    def _match_binary_init(self):
        return self._get_runtime_value('match_binary_init')

    @_match_binary_init.setter
    def _match_binary_init(self, value):
        self._set_runtime_value('match_binary_init', value, template_override=True)

    @property
    def _match_luma_init(self):
        return self._get_runtime_value('match_luma_init')

    @_match_luma_init.setter
    def _match_luma_init(self, value):
        self._set_runtime_value('match_luma_init', value, template_override=True)

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
        self.color = get_color(image, self.area)
        self.image = crop(image, self.area)
        self.is_gif = False
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
        with self.__dict__['_template_lock']:
            state = self._state()
            if state is not None and state.template_override:
                # 不能先读 ``self._match_init``。该属性会在本 worker 尚未加载时
                # 回退到共享缓存；若另一个 worker 已预热模板，当前 worker 修改了
                # area 后就会错误复用旧裁剪图像。
                if state.match_init is True:
                    return
                if self.is_gif:
                    image = []
                    import imageio
                    for frame in imageio.mimread(self.file):
                        frame = frame[:, :, :3].copy() if len(frame.shape) == 3 else frame
                        image.append(crop(frame, self.area))
                    self.image = image
                else:
                    self.image = load_image(self.file, self.area)
                self._match_init = True
                return

            if self.__dict__['_shared_match_init']:
                return
            if self.is_gif:
                image = []
                import imageio
                for frame in imageio.mimread(self.file):
                    frame = frame[:, :, :3].copy() if len(frame.shape) == 3 else frame
                    image.append(crop(frame, self.area))
            else:
                image = load_image(self.file, self.area)
            self._set_shared_value('image', image)
            self._set_shared_value('match_init', True)

    def ensure_binary_template(self):
        """加载二值化资源图像。若需调用 self.match_binary，应先调用此方法。"""
        with self.__dict__['_template_lock']:
            state = self._state()
            if state is not None and state.template_override:
                # 同 ``ensure_template``：局部模板不能被共享初始化标记短路。
                if state.match_binary_init is True:
                    return
            elif self.__dict__['_shared_match_binary_init']:
                return
            self.ensure_template()

            if self.is_gif:
                image_binary = []
                for image in self.image:
                    image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                    _, binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
                    image_binary.append(binary)
            else:
                image_gray = cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY)
                _, image_binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

            if state is not None and state.template_override:
                self.image_binary = image_binary
                self._match_binary_init = True
            else:
                self._set_shared_value('image_binary', image_binary)
                self._set_shared_value('match_binary_init', True)

    def ensure_luma_template(self):
        with self.__dict__['_template_lock']:
            state = self._state()
            if state is not None and state.template_override:
                # 同 ``ensure_template``：局部模板不能被共享初始化标记短路。
                if state.match_luma_init is True:
                    return
            elif self.__dict__['_shared_match_luma_init']:
                return
            self.ensure_template()

            if self.is_gif:
                image_luma = [rgb2luma(image) for image in self.image]
            else:
                image_luma = rgb2luma(self.image)

            if state is not None and state.template_override:
                self.image_luma = image_luma
                self._match_luma_init = True
            else:
                self._set_shared_value('image_luma', image_luma)
                self._set_shared_value('match_luma_init', True)

    def resource_release(self):
        if get_runtime_context() is not None:
            # 线程模式下当前 worker 只能释放自己的动态覆盖；共享模板由宿主
            # 生命周期统一回收，不能被另一 worker 的任务切换清空。
            clear_runtime_state(self, 'button')
            return
        super().resource_release()
        self.__dict__['_shared_color'] = _UNSET
        self.__dict__['_shared_area'] = _UNSET
        self.__dict__['_shared_button'] = _UNSET
        self.__dict__['_shared_name'] = _UNSET
        self.__dict__['_shared_is_gif'] = _UNSET
        self.__dict__['_shared_image'] = None
        self.__dict__['_shared_image_binary'] = None
        self.__dict__['_shared_image_luma'] = None
        self.__dict__['_shared_match_init'] = False
        self.__dict__['_shared_match_binary_init'] = False
        self.__dict__['_shared_match_luma_init'] = False

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
