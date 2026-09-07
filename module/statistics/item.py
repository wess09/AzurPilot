"""掉落物品定义与识别。

定义 Item 类用于表示单个掉落物品及其数量，
通过模板匹配和 OCR 从截图中识别物品图标和数量。
包含物品数量上限校验逻辑。
"""

import numpy as np

import module.config.server as server
from module.base.button import ButtonGrid
from module.base.utils import *
from module.logger import logger
from module.ocr.ocr import Digit, DigitYuv
from module.statistics.utils import *

ITEM_AMOUNT_MAX = {
    'Chip': 50,
    'CognitiveChips': 50,
    'Gem': 100,
    'Gems': 100,
    'Cube': 20,
    'Cubes': 20,
    'Oil': 1000,
    'Coin': 5000,
    'Coins': 5000,
    # 军械测试报告 T4 单次掉落 1~5，超上限读数（如 1 被读成 51）
    # 会触发抹灰版兜底重试修正
    'OrdnanceTestingReportT4': 50,
    # 民用电子元件单次掉落 1~10，超上限读数（如 3 被读成 73）
    # 会触发抹灰版兜底重试修正
    'Consumer_Grade_Electronic_Components': 50,
}
DEFAULT_AMOUNT_MAX = 2147483645


def remove_small_fragments(image, min_height=6, min_area=10, keep_margin=3,
                           fill_background=False, max_digit_gap=None):
    """移除远离数字主体的孤立连通域（图标碎块），保留字形部件。

    专为 ``extract_white_letters`` 的输出设计（深色文字 + 白色背景）。
    获取物品截图中物品图标底部会伸入数量区域，其白色纹理被提取后
    形成远离数字的碎块，可能被 OCR 误读为数字（例如 11 被读成 211）。

    数字笔画高度 11px 以上，但部分字形（如 7 的顶横、笔画的衬线）
    会被拆分成高度不足 6px 的小组件。因此只有「远离」所有大组件
    的小组件才按碎片删除；靠近大组件的小组件视为字形部件保留，
    避免误删导致 77 被读成 27。悬在数字本体左侧、与其无水平重叠
    且面积较大的扁平横条是图标残影（如数字 1 左侧的横条使 1 被
    拼读成 7），同样按碎片删除；面积很小的像素斑点是衬线等抗锯齿
    部件，即使紧贴数字也必须保留。

    默认只删除被判定为碎片组件的像素，其余像素（包括字形抗锯齿
    边缘的中灰像素）原样保留；若把非组件像素一并置为背景，会抹掉
    7 等字形的边缘细节导致 72 被读成 2。fill_background=True 时恢复
    旧行为（非保留像素全部置白），用于首轮读数超上限后的兜底重试。

    max_digit_gap 非空时启用「右侧数字簇」规则：从最右侧的大组件
    出发，水平间隙不超过阈值的组件串成数字簇，其余大组件视为
    图标笔触删除（如图标中的竖笔画被误读成 1 使 2 变 12）。

    Args:
        image (np.ndarray): extract_white_letters 输出的灰度图。
        min_height: 大组件的最小高度。
        min_area: 大组件的最小面积。
        keep_margin: 小组件与大组件包围盒的间距容差（px）。
        fill_background: 是否将非保留像素全部置为背景。
        max_digit_gap: 右侧数字簇的最大水平间隙（px），None 表示关闭。

    Returns:
        np.ndarray: 移除孤立碎块后的灰度图。
    """
    import cv2

    binary = (image < 120).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    big = []
    small = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        bbox = (int(x), int(y), int(x + w), int(y + h))
        if h >= min_height and area >= min_area:
            big.append((i, bbox))
        else:
            small.append((i, bbox, int(area)))

    remove = np.zeros_like(binary)

    # 右侧数字簇：从最右大组件出发按间隙阈值传递聚类，簇外的大组件
    # 视为图标笔触删除（数字间水平间隙小，图标笔触与数字间间隙大）
    if big and max_digit_gap is not None:
        cluster = [max(big, key=lambda t: t[1][2])]
        changed = True
        while changed:
            changed = False
            for i, bbox in big:
                if (i, bbox) in cluster:
                    continue
                x1, _, x2, _ = bbox
                for _, (cx1, _, cx2, _) in cluster:
                    gap = max(cx1 - x2, x1 - cx2)
                    if gap <= max_digit_gap:
                        cluster.append((i, bbox))
                        changed = True
                        break
        for i, bbox in big:
            if (i, bbox) not in cluster:
                remove[labels == i] = 1
        big = cluster

    keep = np.zeros_like(binary)
    for label, _ in big:
        keep[labels == label] = 1
    for label, (x1, y1, x2, y2), area in small:
        near_big = False
        for _, (bx1, by1, bx2, by2) in big:
            # 小组件包围盒外扩 keep_margin 后与大组件相交，视为字形部件
            if (
                x1 - keep_margin < bx2
                and x2 + keep_margin > bx1
                and y1 - keep_margin < by2
                and y2 + keep_margin > by1
            ):
                # 悬在数字本体左侧、无水平重叠的扁平横条是图标残影，
                # 不是字形部件（如 1 左侧的横条使 1 被拼读成 7）；
                # 面积很小的像素斑点是衬线等抗锯齿部件，必须保留
                if x2 <= bx1 and area >= 20:
                    continue
                near_big = True
                break
        if near_big:
            keep[labels == label] = 1
        else:
            remove[labels == label] = 1

    image = image.copy()
    image[remove == 1] = 255
    if fill_background:
        image[keep == 0] = 255
    return image


class AmountOcr(Digit):
    MAX_RETRY = 3
    # 是否过滤图标边缘碎块。委托收入与自律寻敌奖励场景开启，
    # 战斗掉落统计保持原行为。
    remove_fragments = False
    # 碎片过滤的组件阈值，子类可按图像的缩放域覆盖
    # （如自律寻敌奖励页的数量区域先放大 2.67 倍）。
    fragment_min_height = 6
    fragment_min_area = 10
    # 右侧数字簇的最大水平间隙（None 关闭）。奖励页图标中的竖笔画
    # 会被误读成数字（如 2 变 12），按间隙阈值把它排除在数字簇外。
    fragment_max_digit_gap = None

    def pre_process(self, image):
        """预处理图像，提取白色文字。

        Args:
            image (np.ndarray): 输入图像，形状为 (height, width, channel)。

        Returns:
            np.ndarray: 处理后的二值图像，形状为 (width, height)。
        """
        image = extract_white_letters(image, threshold=self.threshold)
        if self.remove_fragments:
            image = remove_small_fragments(
                image,
                min_height=self.fragment_min_height,
                min_area=self.fragment_min_area,
                max_digit_gap=self.fragment_max_digit_gap,
            )
        return image.astype(np.uint8)

    def ocr_with_validation(self, image, item_name=None, direct_ocr=False, trim=True):
        """带验证的 OCR 识别，超过最大值时重试最多 3 次，仍无效则截断末位数字。

        首轮读数超过上限时，若启用了碎片过滤（remove_fragments），
        改用「抹灰版」图像（fill_background=True）重试：抹灰能消除
        靠近数字的图标残影（残影被误读成 S 会使 18 变成 518），
        而首轮保留灰像素的读法可以保住 7 等字形的边缘细节。

        Args:
            image: 单张图像或图像列表。
            item_name: 物品名称，用于查找最大值。
            direct_ocr: 为 True 时跳过裁剪。
            trim: 是否调用 crop_to_text 裁剪空白边框。委托收入场景关闭：
                图标碎片过滤后数字右对齐在原图中，裁剪会改变文字位置，
                导致 OCR 结果变差（例如 71 被读成 2）。

        Returns:
            int: 验证后的数量。
        """
        max_val = ITEM_AMOUNT_MAX.get(item_name, DEFAULT_AMOUNT_MAX)

        if direct_ocr:
            pre_image = self.pre_process(image)
            images = [pre_image]
            alt_images = None
            if self.remove_fragments:
                # 兜底图必须基于 pre_process 的结果（含子类可能的缩放）构建，
                # 直接对原始图像提取会绕过缩放导致识别失效
                alt_images = [
                    remove_small_fragments(
                        pre_image,
                        min_height=self.fragment_min_height,
                        min_area=self.fragment_min_area,
                        max_digit_gap=self.fragment_max_digit_gap,
                        fill_background=True,
                    )
                ]
        else:
            images = [self.pre_process(crop(image, area)) for area in self.buttons]
            alt_images = None
        if trim:
            images = [crop_to_text(i) for i in images]

        result_str = self.cnocr.atomic_ocr_for_single_lines(images, self.alphabet)[0]
        amount = self.after_process(result_str)

        if amount <= max_val:
            return amount

        for retry in range(self.MAX_RETRY):
            logger.warning(f'{item_name} amount {amount} 超过最大值 {max_val}, retry {retry + 1}/{self.MAX_RETRY}')
            if alt_images is not None:
                result_str = self.cnocr.atomic_ocr_for_single_lines(alt_images, self.alphabet)[0]
            else:
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

    def ocr_batch_with_validation(self, image_list, item_names=None, direct_ocr=True, trim=True):
        """批量带验证的 OCR 识别，逐个物品进行校验。

        Args:
            item_names: 物品名称列表，与图像列表一一对应。
            direct_ocr: 为 True 时跳过裁剪。
            trim: 是否调用 crop_to_text 裁剪空白边框。

        Returns:
            list[int]: 验证后的数量列表。
        """
        if item_names is None:
            item_names = [None] * len(image_list)

        results = []
        for image, item_name in zip(image_list, item_names):
            amount = self.ocr_with_validation(image, item_name=item_name, direct_ocr=direct_ocr, trim=trim)
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
        data = load_folder(folder)
        for name, image in data.items():
            if name in self.templates:
                continue
            image = load_image(image)
            image = crop(image, area=self.template_area)
            self.colors[name] = cv2.mean(image)[:3]
            self.templates[name] = image
            self.templates_hit[name] = 0
            if name.isdigit():
                max_digit = max(max_digit, int(name))
            self.next_template_index += 1
        self.next_template_index = max(self.next_template_index, max_digit + 1)
        logger.attr('next_template_index', self.next_template_index)

    def load_cost_template_folder(self, folder):
        """从文件夹加载消耗类型模板图像。

        Args:
            folder (str): 模板文件夹路径。
        """
        max_digit = 0
        data = load_folder(folder)
        for name, image in data.items():
            if name in self.cost_templates:
                continue
            image = load_image(image)
            self.cost_templates[name] = image
            self.cost_templates_hit[name] = 0
            if name.isdigit():
                max_digit = max(max_digit, int(name))
            self.next_cost_template_index += 1
        self.next_cost_template_index = max(self.next_cost_template_index, max_digit + 1)

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
        color = cv2.mean(crop(image, self.template_area))[:3]
        # 优先匹配命中频率高的模板
        names = np.array(list(self.templates.keys()))[np.argsort(list(self.templates_hit.values()))][::-1]
        # 优先匹配已知模板，再匹配数字编号模板
        names = [name for name in names if not name.isdigit()] + [name for name in names if name.isdigit()]
        best_name = None
        best_similarity = similarity
        for name in names:
            if color_similar(color1=color, color2=self.colors[name], threshold=30):
                res = cv2.matchTemplate(image, self.templates[name], cv2.TM_CCOEFF_NORMED)
                _, current_similarity, _, _ = cv2.minMaxLoc(res)
                if current_similarity > best_similarity:
                    best_name = name
                    best_similarity = current_similarity

        if best_name is not None:
            self.templates_hit[best_name] += 1
            return best_name

        self.next_template_index += 1
        name = str(self.next_template_index)
        logger.info(f'新模板: {name}')
        image = crop(image, self.template_area)
        self.colors[name] = cv2.mean(image)[:3]
        self.templates[name] = image
        self.templates_hit[name] = self.templates_hit.get(name, 0) + 1
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
        prev = set(self.templates.keys())
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
        image = item.crop(self.cost_area)
        cost_similarity = lower_template_match_similarity(self.cost_similarity)
        names = np.array(list(self.cost_templates.keys()))[np.argsort(list(self.cost_templates_hit.values()))][::-1]
        for name in names:
            res = cv2.matchTemplate(image, self.cost_templates[name], cv2.TM_CCOEFF_NORMED)
            _, similarity, _, _ = cv2.minMaxLoc(res)
            if similarity > cost_similarity:
                self.cost_templates_hit[name] += 1
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

    def predict(self, image, name=True, amount=True, cost=False, price=False, tag=False, amount_trim=True):
        """预测截图中所有物品的属性。

        Args:
            image (np.ndarray): 截图图像。
            name (bool): 是否预测物品名称。
            amount (bool): 是否预测物品数量。
            cost (bool): 是否预测购买消耗类型。
            price (bool): 是否预测物品价格。
            tag (bool): 是否预测物品标签（如 'catchup'、'bonus'）。
            amount_trim (bool): 数量 OCR 前是否调用 crop_to_text 裁剪。
                委托收入场景配合碎片过滤关闭裁剪，避免文字位置变化导致误读。

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
                amount_images, item_names=item_names, direct_ocr=True, trim=amount_trim
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
