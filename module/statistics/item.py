"""掉落物品定义与识别。

定义 Item 类用于表示单个掉落物品及其数量，
通过模板匹配和 OCR 从截图中识别物品图标和数量。
包含物品数量上限校验逻辑。
"""

import numpy as np
from threading import RLock

import module.config.server as server
from module.base.button import ButtonGrid
from module.base.runtime_context import runtime_state
from module.base.utils import *
from module.logger import logger
from module.ocr.ocr import Digit, DigitYuv
from module.statistics.utils import *

ITEM_AMOUNT_MAX = {
    'Chip': 50,
    'Gem': 100,
    'Cube': 20,
    'Oil': 1000,
    'Coin': 5000,
}
DEFAULT_AMOUNT_MAX = 2147483645


class AmountOcr(Digit):
    MAX_RETRY = 3

    def pre_process(self, image):
        """预处理图像，提取白色文字。

        Args:
            image (np.ndarray): 输入图像，形状为 (height, width, channel)。

        Returns:
            np.ndarray: 处理后的二值图像，形状为 (width, height)。
        """
        image = extract_white_letters(image, threshold=self.threshold)
        return image.astype(np.uint8)

    def ocr_with_validation(self, image, item_name=None, direct_ocr=False):
        """带验证的 OCR 识别，超过最大值时重试最多 3 次，仍无效则截断末位数字。

        Args:
            image: 单张图像或图像列表。
            item_name: 物品名称，用于查找最大值。
            direct_ocr: 为 True 时跳过裁剪。

        Returns:
            int: 验证后的数量。
        """
        max_val = ITEM_AMOUNT_MAX.get(item_name, DEFAULT_AMOUNT_MAX)

        if direct_ocr:
            images = [self.pre_process(image)]
        else:
            images = [self.pre_process(crop(image, area)) for area in self.buttons]
        images = [crop_to_text(i) for i in images]

        result_str = self.cnocr.atomic_ocr_for_single_lines(images, self.alphabet)[0]
        amount = self.after_process(result_str)

        if amount <= max_val:
            return amount

        for retry in range(self.MAX_RETRY):
            logger.warning(f'{item_name} amount {amount} 超过最大值 {max_val}, retry {retry + 1}/{self.MAX_RETRY}')
            result_str = self.cnocr.atomic_ocr_for_single_lines(images, self.alphabet)[0]
            amount = self.after_process(result_str)
            if amount <= max_val:
                logger.info(f'{item_name} amount validated after {retry + 1} retries: {amount}')
                return amount

        if amount > max_val and amount >= 10:
            truncated = int(str(amount)[:-1])
            logger.warning(f'{item_name} amount {amount} still 超过最大值 after {self.MAX_RETRY} retries, '
                          f'truncating to {truncated}')
            return truncated

        return amount

    def ocr_batch_with_validation(self, image_list, item_names=None, direct_ocr=True):
        """批量带验证的 OCR 识别，逐个物品进行校验。

        Args:
            item_names: 物品名称列表，与图像列表一一对应。
            direct_ocr: 为 True 时跳过裁剪。

        Returns:
            list[int]: 验证后的数量列表。
        """
        if item_names is None:
            item_names = [None] * len(image_list)

        results = []
        for image, item_name in zip(image_list, item_names):
            amount = self.ocr_with_validation(image, item_name=item_name, direct_ocr=direct_ocr)
            results.append(amount)
        return results


AMOUNT_OCR = AmountOcr([], threshold=96, name='Amount_ocr')
# 20250814 更新了 UI，但 TW 服务器仍然是旧 UI。
if server.server == 'tw':
    PRICE_OCR = DigitYuv([], letter=(255, 223, 57), threshold=128, name='Price_ocr')
elif server.server == 'jp':
    PRICE_OCR = Digit([], lang='cnocr', letter=(205, 205, 205), threshold=128, name='Price_ocr')
else:
    PRICE_OCR = Digit([], letter=(255, 255, 255), threshold=128, name='Price_ocr')


class Item:
    IMAGE_SHAPE = (96, 96)

    def __init__(self, image, button):
        """初始化物品实例，裁剪并调整图像尺寸。

        Args:
            image: 原始截图。
            button: 按钮对象，包含物品区域信息。
        """
        self.image_raw = image
        self._button = button
        image = crop(image, button.area)
        if image.shape == self.IMAGE_SHAPE:
            self.image = image
        else:
            self.image = cv2.resize(image, self.IMAGE_SHAPE, interpolation=cv2.INTER_CUBIC)
        self.is_valid = self.predict_valid()
        self._name = 'DefaultItem'
        self.amount = 1
        self._cost = 'DefaultCost'
        self.price = 0
        self.tag = None

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        """设置物品名称，自动忽略名称中的数字后缀。

        例如 'Javelin' 和 'Javelin_2' 是不同模板，但输出名称均为 'Javelin'。

        Args:
            value (str): 物品名称，如 'PlateGeneralT3'。
        """
        if '_' in value:
            pre, suffix = value.rsplit('_', 1)
            if suffix.isdigit():
                value = pre
        self._name = value

    @property
    def cost(self):
        return self._cost

    @cost.setter
    def cost(self, value):
        if '_' in value:
            pre, suffix = value.rsplit('_', 1)
            if suffix.isdigit():
                value = pre
        self._cost = value

    def is_known_item(self):
        if self.name == 'DefaultItem':
            return False
        elif self.name.isdigit():
            return False
        else:
            return True

    def __str__(self):
        if self.name != 'DefaultItem' and self.cost == 'DefaultCost':
            name = f'{self.name}_x{self.amount}'
        elif self.name == 'DefaultItem' and self.cost != 'DefaultCost':
            name = f'{self.cost}_x{self.price}'
        else:
            name = f'{self.name}_x{self.amount}_{self.cost}_x{self.price}'

        if self.tag is not None:
            name = f'{name}_{self.tag}'

        return name

    def predict_valid(self):
        return np.mean(rgb2gray(self.image) > 127) > 0.1

    @property
    def button(self):
        return self._button.button

    def crop(self, area):
        return crop(self.image_raw, area_offset(area, offset=self._button.area[:2]))

    def __eq__(self, other):
        # 用于 Filter.apply() 中的去重
        return str(self) == str(other)

    def __hash__(self):
        # 用于合并两次获取物品图像时的去重
        return hash(self.name)


class ItemGrid:
    item_class = Item
    similarity = 0.92
    extract_similarity = 0.92
    cost_similarity = 0.75
    _runtime_fields = frozenset((
        'item_class', 'similarity', 'extract_similarity', 'cost_similarity',
        'amount_ocr', 'price_ocr', 'grids', 'template_area', 'amount_area',
        'cost_area', 'price_area', 'tag_area',
        # 模板数组/颜色表是静态缓存，必须在同一对象的 worker 间共享。
        # 命中计数、索引和识别结果仍属于各自 worker。
        'templates_hit', 'next_template_index',
        'cost_templates_hit', 'next_cost_template_index', 'items',
        # 商店网格在子类构造器中追加的识别器与区域也必须按 worker 隔离。
        'counter_ocr', 'counter_area',
    ))

    def __getattribute__(self, name):
        if name in object.__getattribute__(self, '_runtime_fields'):
            data = object.__getattribute__(self, '__dict__')
            if '_runtime_defaults' in data:
                state = object.__getattribute__(self, '_runtime_state')()
                if state is not None:
                    if name in state:
                        return state[name]
                    return object.__getattribute__(self, '__dict__').get(
                        name, object.__getattribute__(self, '_runtime_defaults').get(name)
                    )
        return object.__getattribute__(self, name)

    def __setattr__(self, name, value):
        if name in self._runtime_fields and '_runtime_defaults' in self.__dict__:
            self._runtime_defaults.setdefault(name, value)
            state = self._runtime_state()
            if state is not None:
                state[name] = value
                return
        object.__setattr__(self, name, value)

    def _runtime_state(self):
        defaults = self.__dict__.get('_runtime_defaults')
        if defaults is None:
            return None

        def factory():
            state = {}
            for name, value in defaults.items():
                if isinstance(value, dict):
                    state[name] = dict(value)
                elif isinstance(value, list):
                    state[name] = list(value)
                else:
                    state[name] = value
            # 共享模板可能已由另一个 worker 加载；首次创建本 worker 状态时
            # 只初始化轻量命中计数，不复制模板图像和颜色表。
            templates = object.__getattribute__(self, 'templates')
            cost_templates = object.__getattribute__(self, 'cost_templates')
            lock = object.__getattribute__(self, '_template_lock')
            # 模板可以由别的 worker 追加。只在锁内取得键快照，避免初始化
            # 命中表时迭代到正在变化的字典。
            with lock:
                template_names = tuple(templates)
                cost_template_names = tuple(cost_templates)
            template_hits = state.setdefault('templates_hit', {})
            cost_template_hits = state.setdefault('cost_templates_hit', {})
            for name in template_names:
                template_hits.setdefault(name, 0)
            for name in cost_template_names:
                cost_template_hits.setdefault(name, 0)
            return state

        return runtime_state(self, 'item_grid', factory)

    @staticmethod
    def _max_numeric_template_name(templates):
        """返回共享模板中最大的数字名称；没有数字模板时返回 0。"""
        numeric_names = [int(name) for name in templates if str(name).isdigit()]
        return max(numeric_names, default=0)

    def _sync_runtime_template_state(self):
        """将新增共享模板同步到当前 worker 的轻量命中表。"""
        state = self._runtime_state()
        if state is None:
            return None

        lock = object.__getattribute__(self, '_template_lock')
        templates = object.__getattribute__(self, 'templates')
        cost_templates = object.__getattribute__(self, 'cost_templates')
        with lock:
            template_hits = state['templates_hit']
            cost_template_hits = state['cost_templates_hit']
            for name in templates:
                template_hits.setdefault(name, 0)
            for name in cost_templates:
                cost_template_hits.setdefault(name, 0)
            state['next_template_index'] = max(
                state['next_template_index'],
                self._max_numeric_template_name(templates),
            )
            state['next_cost_template_index'] = max(
                state['next_cost_template_index'],
                self._max_numeric_template_name(cost_templates),
            )
        return state

    def __init__(self, grids, templates, template_area=(40, 21, 89, 70), amount_area=(60, 71, 91, 92),
                 cost_area=(6, 123, 84, 166), price_area=(52, 132, 132, 156), tag_area=(81, 4, 91, 8)):
        """初始化物品网格，加载模板并设置各子区域坐标。

        Args:
            grids (ButtonGrid): 按钮网格，定义物品槽位布局。
            templates (dict): 模板字典，键为物品名称，值为模板图像。
            template_area (tuple): 模板匹配区域坐标。
            amount_area (tuple): 数量 OCR 区域坐标。
            cost_area (tuple): 消耗类型匹配区域坐标。
            price_area (tuple): 价格 OCR 区域坐标。
            tag_area (tuple): 标签检测区域坐标。
        """
        self.amount_ocr = AMOUNT_OCR
        self.price_ocr = PRICE_OCR
        self.grids = grids
        self.template_area = template_area
        self.amount_area = amount_area
        self.cost_area = cost_area
        self.price_area = price_area
        self.tag_area = tag_area

        # 模板数组和颜色表为跨 worker 的只读/追加缓存；命中计数不放在这里。
        self._template_lock = RLock()
        self.colors = {}
        self.templates = {}
        self.templates_hit = {}
        self.next_template_index = len(self.templates.keys())
        for name, template in templates.items():
            self.templates[name] = crop(template.image, area=self.template_area)
            self.templates_hit[name] = 0
            if name.isdigit() and int(name) > self.next_template_index:
                self.next_template_index = int(name)

        self.cost_templates = {}
        self.cost_templates_hit = {}
        self.next_cost_template_index = len(self.cost_templates.keys())

        self.items = []
        self._runtime_defaults = {
            name: object.__getattribute__(self, name)
            for name in self._runtime_fields
            if hasattr(self, name)
        }

    def _load_image(self, image):
        """从截图中加载所有有效物品。

        Args:
            image (np.ndarray): 截图图像。
        """
        self.items = []
        for button in self.grids.buttons:
            item = self.item_class(image, button)
            if item.is_valid:
                self.items.append(item)

    def load_template_folder(self, folder):
        """从文件夹加载物品模板图像。

        Args:
            folder (str): 模板文件夹路径。
        """
        logger.info(f'加载模板文件夹: {folder}')
        max_digit = 0
        previous_index = self.next_template_index
        data = load_folder(folder)
        added = []
        templates = object.__getattribute__(self, 'templates')
        colors = object.__getattribute__(self, 'colors')
        with object.__getattribute__(self, '_template_lock'):
            for name, image in data.items():
                if name in templates:
                    continue
                image = load_image(image)
                image = crop(image, area=self.template_area)
                colors[name] = cv2.mean(image)[:3]
                templates[name] = image
                added.append(name)
                if name.isdigit():
                    max_digit = max(max_digit, int(name))
        # 当前 worker 仅补充轻量计数表；其他 worker 在下次匹配前同步。
        self._sync_runtime_template_state()
        if added:
            self.next_template_index = max(
                previous_index + len(added),
                max_digit + 1,
                len(templates),
            )
        logger.attr('next_template_index', self.next_template_index)

    def load_cost_template_folder(self, folder):
        """从文件夹加载消耗类型模板图像。

        Args:
            folder (str): 模板文件夹路径。
        """
        max_digit = 0
        previous_index = self.next_cost_template_index
        added_count = 0
        data = load_folder(folder)
        cost_templates = object.__getattribute__(self, 'cost_templates')
        with object.__getattribute__(self, '_template_lock'):
            for name, image in data.items():
                if name in cost_templates:
                    continue
                image = load_image(image)
                cost_templates[name] = image
                added_count += 1
                if name.isdigit():
                    max_digit = max(max_digit, int(name))
        self._sync_runtime_template_state()
        if added_count:
            self.next_cost_template_index = max(
                previous_index + added_count,
                max_digit + 1,
                len(cost_templates),
            )

    def match_template(self, image, similarity=None):
        """匹配物品模板，优先尝试命中频率最高的模板。

        未匹配到已有模板时，会自动创建新模板并分配递增 ID。

        Args:
            image (np.ndarray): 物品图像。
            similarity (float): 匹配相似度阈值。

        Returns:
            str: 模板名称。
        """
        if similarity is None:
            similarity = self.similarity
        similarity = lower_template_match_similarity(similarity)
        self._sync_runtime_template_state()
        templates = object.__getattribute__(self, 'templates')
        colors = object.__getattribute__(self, 'colors')
        lock = object.__getattribute__(self, '_template_lock')
        state = self._runtime_state()
        hit_table = state['templates_hit'] if state is not None else self.templates_hit
        # 只复制键和数组引用，避免匹配期间持有写锁或复制大图像。
        with lock:
            names = list(templates)
            template_snapshot = {name: templates[name] for name in names}
            color_snapshot = {name: colors.get(name) for name in names}
        names.sort(key=lambda name: hit_table.get(name, 0), reverse=True)
        # 优先匹配已知模板，再匹配数字编号模板。
        names = [name for name in names if not str(name).isdigit()] + [
            name for name in names if str(name).isdigit()
        ]
        color = cv2.mean(crop(image, self.template_area))[:3]
        best_name = None
        best_similarity = similarity
        for name in names:
            template_color = color_snapshot.get(name)
            template = template_snapshot.get(name)
            if template_color is None or template is None:
                continue
            if color_similar(color1=color, color2=template_color, threshold=30):
                res = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
                _, current_similarity, _, _ = cv2.minMaxLoc(res)
                if current_similarity > best_similarity:
                    best_name = name
                    best_similarity = current_similarity

        if best_name is not None:
            hit_table[best_name] = hit_table.get(best_name, 0) + 1
            return best_name

        # 追加模板时重新在共享表中分配编号，避免两个 worker 使用各自旧索引
        # 写入同名模板并互相覆盖。
        new_image = crop(image, self.template_area)
        with lock:
            next_index = self._max_numeric_template_name(templates) + 1
            name = str(next_index)
            while name in templates:
                next_index += 1
                name = str(next_index)
            colors[name] = cv2.mean(new_image)[:3]
            templates[name] = new_image
        self._sync_runtime_template_state()
        hit_table[name] = hit_table.get(name, 0) + 1
        self.next_template_index = max(self.next_template_index, next_index)
        logger.info(f'新模板: {name}')
        return name

    def extract_template(self, image, folder=None):
        """从截图中提取新模板。

        Args:
            image (np.ndarray): 截图图像。
            folder (str): 提供时将新模板保存到该文件夹。

        Returns:
            dict: 新发现的模板，键为模板名称，值为图像。
        """
        self._load_image(image)
        templates = object.__getattribute__(self, 'templates')
        lock = object.__getattribute__(self, '_template_lock')
        # 与 ``match_template`` 的共享写入互斥，避免迭代过程中模板字典被扩容。
        with lock:
            prev = set(templates)
        new = {}
        for item in self.items:
            name = self.match_template(item.image, similarity=self.extract_similarity)
            if name not in prev:
                new[name] = item.image

        if folder is not None:
            for name, im in new.items():
                save_image(im, os.path.join(folder, f'{name}.png'))

        return new

    def match_cost_template(self, item):
        """匹配消耗类型模板，优先尝试命中频率最高的模板。

        未匹配到时返回 None，表示该物品无效。

        Args:
            item (Item): 物品实例。

        Returns:
            str: 模板名称，未匹配到返回 None。
        """
        self._sync_runtime_template_state()
        cost_templates = object.__getattribute__(self, 'cost_templates')
        lock = object.__getattribute__(self, '_template_lock')
        state = self._runtime_state()
        hit_table = state['cost_templates_hit'] if state is not None else self.cost_templates_hit
        with lock:
            names = list(cost_templates)
            template_snapshot = {name: cost_templates[name] for name in names}
        names.sort(key=lambda name: hit_table.get(name, 0), reverse=True)

        image = item.crop(self.cost_area)
        cost_similarity = lower_template_match_similarity(self.cost_similarity)
        for name in names:
            template = template_snapshot.get(name)
            if template is None:
                continue
            res = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
            _, match_similarity, _, _ = cv2.minMaxLoc(res)
            if match_similarity > cost_similarity:
                hit_table[name] = hit_table.get(name, 0) + 1
                return name

        # 不自动生成新的消耗模板，未匹配到则视为无效物品
        return None

    @staticmethod
    def predict_tag(image):
        """根据标签区域颜色预测物品标签。

        通过颜色相似度判断：蓝色为 catchup，青色为 bonus，红色为 event。

        Args:
            image (np.ndarray): 物品的标签区域图像。

        Returns:
            str: 标签名称（'catchup'、'bonus'、'event'），无法识别返回 None。
        """
        threshold = 50
        color = cv2.mean(np.array(image))[:3]
        if color_similar(color1=color, color2=(49, 125, 222), threshold=threshold):
            # 蓝色
            return 'catchup'
        elif color_similar(color1=color, color2=(33, 199, 239), threshold=threshold):
            # 青色
            return 'bonus'
        elif color_similar(color1=color, color2=(255, 85, 41), threshold=threshold):
            # 红色
            return 'event'
        else:
            return None

    def predict(self, image, name=True, amount=True, cost=False, price=False, tag=False):
        """预测截图中所有物品的属性。

        Args:
            image (np.ndarray): 截图图像。
            name (bool): 是否预测物品名称。
            amount (bool): 是否预测物品数量。
            cost (bool): 是否预测购买消耗类型。
            price (bool): 是否预测物品价格。
            tag (bool): 是否预测物品标签（如 'catchup'、'bonus'）。

        Returns:
            list[Item]: 物品列表。
        """
        self._load_image(image)
        if name:
            name_list = [self.match_template(item.image) for item in self.items]
            for item, n in zip(self.items, name_list):
                item.name = n
        if amount:
            amount_images = [item.crop(self.amount_area) for item in self.items]
            item_names = [item.name for item in self.items]
            amount_list = self.amount_ocr.ocr_batch_with_validation(
                amount_images, item_names=item_names, direct_ocr=True
            )
            for item, a in zip(self.items, amount_list):
                item.amount = a
        if cost:
            cost_list = [self.match_cost_template(item) for item in self.items]
            self.items = [item for item, c in zip(self.items, cost_list) if c is not None]
            cost_list = [c for c in cost_list if c is not None]
            for item, c in zip(self.items, cost_list):
                item.cost = c
        if price and len(self.items):
            price_list = [item.crop(self.price_area) for item in self.items]
            price_list = self.price_ocr.ocr(price_list, direct_ocr=True)
            for item, p in zip(self.items, price_list):
                item.price = p
        if tag:
            tag_list = [self.predict_tag(item.crop(self.tag_area)) for item in self.items]
            for item, t in zip(self.items, tag_list):
                item.tag = t

        # 过滤掉价格异常的物品
        items = [item for item in self.items if not (price and item.price <= 0)]
        diff = len(self.items) - len(items)
        if diff > 0:
            logger.warning(f'[统计-物品] 忽略 {diff} 个物品，因为价格<=0')
            self.items = items

        return self.items
