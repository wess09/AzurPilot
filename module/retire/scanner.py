"""
船坞舰船扫描系统。

提供船坞页面中舰船属性的多维度扫描能力，包括等级、情绪、稀有度、
舰队归属和状态识别。通过组合多个子扫描器 (LevelScanner、
EmotionScanner、RarityScanner、FleetScanner、StatusScanner)
实现舰船信息的批量采集。

支持单页扫描 (ShipScanner) 和跨页滚动扫描 (DockScanner)，
后者通过灰度图标准差定位卡片间隙，自动滚动并去重，完成全船坞扫描。
DHash 感知哈希用于跨页去重判断。
"""

import os
import time
from abc import ABCMeta, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple, Union

import cv2
import numpy as np

import module.config.server as server
from module.base.button import ButtonGrid
from module.base.utils import (color_similar, crop, extract_letters, get_color,
                               image_color_count, limit_in,
                               random_normal_distribution_int,
                               random_rectangle_point)
from module.combat.level import LevelOcr
from module.logger import logger
from module.ocr.ocr import Digit, Ocr
from module.retire.assets import (DOCK_CHECK, SHIP_DETAIL_CHECK,
                                  TEMPLATE_FLEET_1, TEMPLATE_FLEET_2,
                                  TEMPLATE_FLEET_3, TEMPLATE_FLEET_4,
                                  TEMPLATE_FLEET_5, TEMPLATE_FLEET_6,
                                  TEMPLATE_IN_BATTLE, TEMPLATE_IN_COMMISSION, TEMPLATE_IN_HARD,
                                  TEMPLATE_IN_EVENT_FLEET)
from module.retire.dock import (CARD_EMOTION_GRIDS, CARD_EMOTION_STATUS_GRIDS, CARD_GRIDS,
                                CARD_LEVEL_GRIDS, CARD_RARITY_GRIDS, DOCK_SCROLL,
                                EMOTION_RED, EMOTION_YELLOW, EMOTION_GREEN)
from module.retire.ship_name import ShipNameMatcher


class EmotionDigit(Digit):
    """情绪值 OCR 识别器，针对船坞卡片的情绪数字区域优化。

    针对 JP 服务器特殊处理白色文字提取，
    并修正唐斯头发区域的随机误识别 (044 -> 0)。
    """
    def pre_process(self, image):
        """对情绪数字区域进行预处理。

        Args:
            image (np.ndarray): 输入图像。

        Returns:
            np.ndarray: 预处理后的图像。
        """
        if server.server == 'jp':
            image_gray = extract_letters(image, letter=(255, 255, 255), threshold=self.threshold)
            right_side = np.nonzero(image_gray[0:16, :].max(axis=0) > 192)[-1]
            for i, col in enumerate(right_side):
                if i < col:
                    break
            image = image[:, :i]
        image = super().pre_process(image)
        return image

    def after_process(self, result):
        """对情绪数字识别结果进行后处理。

        Args:
            result (str): 原始识别字符串。

        Returns:
            int: 修正后的情绪数值。
        """
        # 唐斯头发区域的随机 OCR 误识别
        # DOCK_EMOTION_OCR 识别结果 "044" 修正为 "44"
        if result == '044' or result == 'D44':
            result = '0'

        result = super().after_process(result)
        if result > 150 and result % 10 in [1, 4]:
            result //= 10

        return result


@dataclass(frozen=True)
class Ship:
    rarity: str = ''
    level: int = 0
    emotion: int = 0
    fleet: int = 0
    status: str = ''
    button: Any = None
    hash_: str = field(default='', repr=False)

    def satisfy_limitation(self, limitation) -> bool:
        """检查舰船是否满足筛选条件。

        遍历舰船的所有属性，与 limitation 中的限制逐一比对。
        str/int 类型要求精确匹配，tuple 表示范围，list 表示枚举。

        Args:
            limitation: 筛选条件字典，key 为属性名，value 为限制值。

        Returns:
            bool: 是否满足所有限制条件。
        """
        for key in self.__dict__:
            value = limitation.get(key)
            if self.__dict__[key] is not None and value is not None:
                # str 和 int 要求精确匹配
                if isinstance(value, (str, int)):
                    if value == 'any':
                        continue
                    if self.__dict__[key] != value:
                        return False
                # tuple 表示范围限制
                elif isinstance(value, tuple):
                    if not (value[0] <= self.__dict__[key] <= value[1]):
                        return False
                # list 表示枚举限制
                elif isinstance(value, list):
                    if self.__dict__[key] not in value:
                        return False

        return True


class DHash:
    """感知哈希 (Difference Hash) 实现，用于图像去重。

    通过比较相邻像素生成哈希值，以汉明距离判断两张图像是否相似。
    用于 DockScanner 跨页扫描时的去重判断。

    Attributes:
        EQ_THRES (int): 哈希相等的距离阈值，默认 30。
        code (str): 生成的十六进制哈希字符串。
    """
    EQ_THRES: int = 30

    def __init__(self, image, size=8) -> None:
        self.code = DHash.gen_hash(image, size)

    @staticmethod
    def gen_hash(image, size=8) -> str:
        """生成图像的 DHash 感知哈希十六进制字符串。

        Args:
            image (np.ndarray): 输入图像。
            size (int): 缩放网格边长，默认 8。

        Returns:
            str: 拼接后的行与列差异哈希十六进制字符串。
        """
        if len(image.shape) > 2:
            image = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        image = cv2.resize(image, (size + 1, size + 1))
        row_diff = np.packbits(image[:-1, :-1] > image[1:, :-1])
        col_diff = np.packbits(image[:-1, :-1] > image[:-1, 1:])
        row_hash: str = ''.join([f'{i:>02x}' for i in row_diff])
        col_hash: str = ''.join([f'{i:>02x}' for i in col_diff])

        return f'{row_hash}{col_hash}'

    @staticmethod
    def distance(__x, __y) -> int:
        """计算两个 DHash 之间的汉明距离。

        Args:
            __x (DHash | str): 第一个哈希对象或哈希字符串。
            __y (DHash | str): 第二个哈希对象或哈希字符串。

        Returns:
            int: 汉明距离（不同比特位的个数）。
        """
        if isinstance(__x, DHash) and isinstance(__y, DHash):
            __x, __y = int(__x.code, 16), int(__y.code, 16)
        elif isinstance(__x, str) and isinstance(__y, str):
            __x, __y = int(__x, 16), int(__y, 16)

        return bin(__x ^ __y).count('1')

    def __eq__(self, __o: object) -> bool:
        return type(self) == type(__o) and DHash.distance(self, __o) < DHash.EQ_THRES

    def __repr__(self) -> str:
        return self.code


class Scanner(metaclass=ABCMeta):
    """扫描器抽象基类。

    定义船坞卡片属性扫描的通用接口，子扫描器 (LevelScanner、
    RarityScanner 等) 继承此类并实现 _scan() 方法。

    Attributes:
        _results (List): 缓存的扫描结果。
        _enabled (bool): 扫描器是否启用，禁用时返回全 None 列表。
        _disabled_value (List[None]): 禁用时的默认返回值。
        grids (ButtonGrid): 卡片属性区域的按钮网格。
    """
    _results: List = None
    _enabled: bool = True
    _disabled_value: List[None] = [None] * 14
    grids: ButtonGrid = None

    @property
    def results(self) -> List:
        return self._results

    @abstractmethod
    def _scan(self, image) -> List:
        pass

    @abstractmethod
    def limit_value(self, value) -> Any:
        pass

    def clear(self) -> None:
        """清除所有缓存的扫描结果。"""
        self._results.clear()

    def scan(self, image, cached=False, output=False) -> Union[List, None]:
        """执行扫描，返回结果列表。

        启用时返回真实扫描结果，禁用时返回全 None 列表。
        多次扫描场景建议使用 cached=True 缓存结果。

        Args:
            image: 截图图像。
            cached: 是否将结果追加到缓存。
            output: 是否将结果逐条输出到日志。

        Returns:
            list 或 None: cached=False 时返回结果列表，cached=True 时返回 None。
        """
        results: List = self._scan(image) if self._enabled else self._disabled_value

        if output:
            for result in results:
                logger.info(f'{result}')

        if cached:
            self._results.extend(results)
        else:
            return results

    def move(self, vector) -> None:
        """移动网格坐标，同步更新内部 ButtonGrid。"""
        self.grids = self.grids.move(vector)

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False


class LevelScanner(Scanner):
    """等级扫描器，通过 OCR 识别船坞卡片上显示的舰船等级。"""
    def __init__(
        self,
        grid_shape: Tuple[int, int] = (7, 2),
        excluded_positions: Tuple[Tuple[int, int], ...] = (),
    ) -> None:
        super().__init__()
        self._results = []
        card_grids = ButtonGrid(
            origin=CARD_GRIDS.origin,
            delta=CARD_GRIDS.delta,
            button_shape=CARD_GRIDS.button_shape,
            grid_shape=grid_shape,
            name='CARD',
        )
        level_origin = CARD_LEVEL_GRIDS.origin - CARD_GRIDS.origin
        level_area = tuple(np.append(level_origin, level_origin + CARD_LEVEL_GRIDS.button_shape))
        self.grids = card_grids.crop(area=level_area, name='LEVEL')
        self.excluded_positions = set(excluded_positions)
        self.ocr_model = LevelOcr(self._buttons(),
                                  name='DOCK_LEVEL_OCR', threshold=64)

    def _buttons(self) -> List:
        return [
            button
            for x, y, button in self.grids.generate()
            if (x, y) not in self.excluded_positions
        ]

    def _scan(self, image) -> List:
        return self.ocr_model.ocr(image)

    def limit_value(self, value) -> int:
        return limit_in(value, 1, 125)
    
    def move(self, vector) -> None:
        super().move(vector)
        self.ocr_model.buttons = self._buttons()


class EmotionScanner(Scanner):
    """情绪扫描器，通过 OCR 识别舰船情绪值。

    结合 EmotionStatusScanner 的颜色状态进行交叉校正，
    修正 OCR 在低情绪场景下的误识别。
    """
    def __init__(self) -> None:
        super().__init__()
        self._results = []
        self.grids = CARD_EMOTION_GRIDS
        if server.server != 'jp':
            self.ocr_model = EmotionDigit(self.grids.buttons,
                                      name='DOCK_EMOTION_OCR', threshold=176)
        else:
            self.ocr_model = EmotionDigit(self.grids.buttons,
                                      name='DOCK_EMOTION_OCR', 
                                      letter=(201, 201, 201), 
                                      threshold=176)

    def _scan(self, image) -> List:
        results = []
        for emotion, emotion_status in zip(
                self.ocr_model.ocr(image),
                EmotionStatusScanner().scan(image)):
            if emotion_status == 'red':
                emotion = 0
            elif emotion_status == 'yellow':
                if emotion > 30:
                    emotion //= 10
            elif emotion_status == 'green':
                if emotion > 40:
                    emotion //= 10
            results.append(emotion)
        logger.attr('船坞心情OCR', results)
        return results

    def limit_value(self, value) -> int:
        return limit_in(value, 0, 150)

    def move(self, vector) -> None:
        super().move(vector)
        self.ocr_model.buttons = [button.area for button in self.grids.buttons]


class EmotionStatusScanner(Scanner):
    """情绪状态扫描器，通过颜色识别情绪指示灯。

    检测船坞卡片右上角指示灯的颜色：红、黄、绿，分别对应
    不同的情绪区间。结果用于 EmotionScanner 的交叉校正。
    """
    def __init__(self) -> None:
        super().__init__()
        self._results = []
        self.grids = CARD_EMOTION_STATUS_GRIDS
        self.value_list: List[str] = ['red', 'yellow', 'green', 'unknown']

    def get_emotion_status(self, image) -> str:
        """获取舰船卡片右上角的情绪状态指示灯颜色。

        通过统计图像中特定颜色的像素数量来判断情绪状态：
            'yellow': 1 <= emotion <= 30
            'green': 31 <= emotion <= 40
            'red': emotion = 0
            'unknown': emotion > 40

        Args:
            image: 裁剪后的情绪状态指示灯区域图像。

        Returns:
            str: 情绪状态，取值为 'yellow'、'green'、'red' 或 'unknown'。
        """
        if image_color_count(image, color=EMOTION_YELLOW, count=300):
            return 'yellow'
        elif image_color_count(image, color=EMOTION_GREEN, count=300):
            return 'green'
        elif image_color_count(image, color=EMOTION_RED, count=300):
            return 'red'
        else:
            return 'unknown'

    def _scan(self, image) -> List:
        results = [self.get_emotion_status(crop(image, button.area, copy=False))
                   for button in self.grids.buttons]
        logger.attr('船坞心情状态', results)
        return results

    def limit_value(self, value) -> str:
        return value if value in self.value_list else 'any'


class RarityScanner(Scanner):
    """稀有度扫描器，通过卡片顶部颜色条判断舰船稀有度。

    稀有度映射：common(灰)、rare(蓝)、elite(紫)、super_rare(金)。
    彩虹稀有度因颜色差异过大标记为 unknown。
    """
    def __init__(self) -> None:
        super().__init__()
        self._results = []
        self.grids = CARD_RARITY_GRIDS
        self.value_list: List[str] = ['common', 'rare', 'elite', 'super_rare']

    def color_to_rarity(self, color: Tuple[int, int, int]) -> str:
        """将卡片颜色转换为舰船稀有度。

        稀有度分为 common、rare、elite、super_rare、unknown 五种。
        彩虹（ultra）稀有度因颜色差异过大，标记为 'unknown'。

        Args:
            color: RGB 颜色元组 (r, g, b)。

        Returns:
            str: 稀有度字符串。
        """
        if color_similar(color, (171, 174, 186)):
            return 'common'
        elif color_similar(color, (106, 194, 248)):
            return 'rare'
        elif color_similar(color, (151, 134, 254)):
            return 'elite'
        elif color_similar(color, (247, 221, 101)):
            return 'super_rare'
        else:
            # 彩虹稀有度颜色差异过大，无法统一识别
            return 'unknown'

    def _scan(self, image) -> List:
        return [self.color_to_rarity(get_color(image, button.area))
                for button in self.grids.buttons]

    def limit_value(self, value) -> str:
        return value if value in self.value_list else 'any'


class FleetScanner(Scanner):
    """舰队归属扫描器，通过模板匹配识别舰船所属的舰队编号。

    对卡片左下角的舰队标识进行灰度二值化预处理后，
    逐一匹配 Fleet 1-6 的模板图像。未匹配到则返回 0（不在编队）。
    """
    TEMPLATE_SIMILARITY = 0.75

    def __init__(
        self,
        grid_shape: Tuple[int, int] = (7, 2),
        excluded_positions: Tuple[Tuple[int, int], ...] = (),
    ) -> None:
        """初始化舰队归属扫描器。

        Args:
            grid_shape: 待扫描的卡片网格。退役流程保持默认的 7×2；
                舰队管理可使用 7×3 扫描当前页面的第三行卡片。
            excluded_positions: 不扫描的卡片坐标，格式为 ``(列, 行)``。
        """
        super().__init__()
        self._results = []
        card_grids = ButtonGrid(
            origin=CARD_GRIDS.origin,
            delta=CARD_GRIDS.delta,
            button_shape=CARD_GRIDS.button_shape,
            grid_shape=grid_shape,
            name='CARD',
        )
        self.grids = card_grids.crop(area=(0, 117, 35, 162), name='FLEET')
        self.excluded_positions = set(excluded_positions)
        self.templates = {
            TEMPLATE_FLEET_1: 1,
            TEMPLATE_FLEET_2: 2,
            TEMPLATE_FLEET_3: 3,
            TEMPLATE_FLEET_4: 4,
            TEMPLATE_FLEET_5: 5,
            TEMPLATE_FLEET_6: 6
        }

    def pre_process(self, image):
        """对舰队编号图像进行预处理，提升模板匹配效果。

        将图像转为灰度后二值化，使数字与背景分离更明显。
        若需更新 TEMPLATE_FLEET 素材，必须先执行此预处理。

        Args:
            image (np.ndarray): 输入图像。

        Returns:
            np.ndarray: 二值化处理后的三通道图像。
        """
        _, g, _ = cv2.split(image)
        _, image = cv2.threshold(g, 205, 255, cv2.THRESH_BINARY)
        image = cv2.merge([image, image, image])

        return image

    def _match(self, image) -> int:
        """通过模板匹配识别舰船所属舰队编号。

        彩虹稀有度卡片因闪光干扰，识别效果较差。
        未匹配到任何舰队时返回 0（不在任何编队中）。

        Args:
            image (np.ndarray): 裁剪后的舰队标识区域图像。

        Returns:
            int: 舰队编号 (1-6)，未匹配返回 0。
        """
        for template, fleet in self.templates.items():
            if template.match(image, similarity=self.TEMPLATE_SIMILARITY):
                return fleet
        return 0

    def _scan(self, image) -> List:
        image = self.pre_process(image)
        image_list = [
            crop(image, button.area)
            for x, y, button in self.grids.generate()
            if (x, y) not in self.excluded_positions
        ]

        return [self._match(image) for image in image_list]

    def limit_value(self, value) -> int:
        return limit_in(value, 0, 6)


class FleetNameScanner(Scanner):
    """识别船坞舰名，仅依据精确身份或唯一截断补全，未确认时保留原文。"""
    OCR_LANG = {
        'cn': 'ppocr_v6',
        'en': 'ppocr_v6',
        'jp': 'jp',
        'tw': 'tw',
    }

    class NameOcr(Ocr):
        """提取白色和婚舰粉色名称，统一为黑白图像。"""
        PINK_LETTER = (255, 170, 206)
        PINK_THRESHOLD = 108
        TEXT_ROWS = (4, 23)
        TEXT_LEFT = 4

        @staticmethod
        def _remove_edge_noise(image):
            """移除名称区域左右边缘残留的卡片边框像素。"""
            count, labels, stats, _ = cv2.connectedComponentsWithStats(
                (image < 120).astype(np.uint8), connectivity=8
            )
            for label in range(1, count):
                x, _, component_width, _, _ = stats[label]
                if x == 0 or x + component_width == image.shape[1]:
                    image[labels == label] = 255
            return image

        def pre_process(self, image):
            white = extract_letters(image, letter=self.letter, threshold=self.threshold)
            pink = extract_letters(image, letter=self.PINK_LETTER, threshold=self.PINK_THRESHOLD)
            merged = cv2.min(white, pink)
            merged = merged[self.TEXT_ROWS[0]:self.TEXT_ROWS[1], self.TEXT_LEFT:]
            return self._remove_edge_noise(merged)

    def __init__(
        self,
        grid_shape: Tuple[int, int] = (7, 2),
        excluded_positions: Tuple[Tuple[int, int], ...] = (),
    ) -> None:
        super().__init__()
        self._results = []
        card_grids = ButtonGrid(
            origin=CARD_GRIDS.origin,
            delta=CARD_GRIDS.delta,
            button_shape=CARD_GRIDS.button_shape,
            grid_shape=grid_shape,
            name='CARD',
        )
        self.grids = card_grids.crop(area=(-10, 160, 142, 190), name='SHIP_NAME')
        self.excluded_positions = set(excluded_positions)
        self.ocr_model = self.NameOcr(
            self._buttons(),
            lang=self.OCR_LANG[server.server],
            threshold=128,
            name='FLEET_SHIP_NAME',
        )
        self.name_matcher = ShipNameMatcher(server.server)

    def _buttons(self) -> List:
        return [
            button.area
            for x, y, button in self.grids.generate()
            if (x, y) not in self.excluded_positions
        ]

    def _scan(self, image) -> List:
        names = self.ocr_model.ocr(image)
        names = names if isinstance(names, list) else [names]
        resolved = [self.name_matcher.resolve(name) for name in names]
        corrected = [name for name, _ in resolved]
        unresolved = [i for i, (_, status) in enumerate(resolved) if self.name_matcher.names
                      if status not in ('exact', 'prefix', 'missing_catalog')]
        if unresolved:
            # 同一截图、相同名称裁剪；只对未确认名称追加一次原彩色识别，不放大猜字。
            regions = [crop(image, self.ocr_model.buttons[i])[
                self.NameOcr.TEXT_ROWS[0]:self.NameOcr.TEXT_ROWS[1], self.NameOcr.TEXT_LEFT:
            ] for i in unresolved]
            retries = self.ocr_model.cnocr.atomic_ocr_for_single_lines(regions, None)
            for i, retry in zip(unresolved, retries):
                retry = ''.join(retry)
                candidate = self.name_matcher.retry_candidate(names[i], retry)
                if candidate is not None:
                    corrected[i] = candidate
                    logger.info(f'[舰队扫描-OCR] 彩色复识别确认: {names[i]!r} -> {candidate!r}')
                else:
                    logger.info(f'[舰队扫描-OCR] 名称未确认，保留原文: {names[i]!r}，'
                                f'依据={resolved[i][1]}，彩色结果={retry!r}')
        for raw, name, (_, status) in zip(names, corrected, resolved):
            if raw != name and status in ('exact', 'prefix'):
                logger.info(f'[舰队扫描-OCR] 舰娘名确认: {raw!r} -> {name!r}，依据={status}')
            elif status == 'missing_catalog':
                logger.info(f'[舰队扫描-OCR] 名单不可用，保留原文: {raw!r}')
        return corrected

    def limit_value(self, value) -> str:
        return value

    def move(self, vector) -> None:
        super().move(vector)
        self.ocr_model.buttons = self._buttons()


class FleetEmotionDigit(Digit):
    """舰队信息专用心情解析：未知为 None，不截位猜数或把空白当零。"""

    def prepare_low_emotion(self, image):
        """保留原生一、两位数字，排除短标签右侧的立绘和底部亮线。"""
        image = image[:20, :17]
        gray = self.pre_process(image)
        _, _, components, _ = cv2.connectedComponentsWithStats((gray < 160).astype(np.uint8))
        clean = np.zeros_like(image)
        for x, y, width, height, _ in components[1:]:
            # 720p 心情数字约高15像素；立绘往往贯穿裁剪框或宽于单个数字。
            if 10 <= height <= 20 and width <= 8 and y <= 7:
                clean[y:y + height, x:x + width] = image[y:y + height, x:x + width]
        return clean

    def after_process(self, result):
        if not result or not result.isascii() or not result.isdigit():
            return None
        if len(result) > 1 and result.startswith('0'):
            return None
        value = int(result)
        return value if 0 <= value <= 150 else None


class FleetEmotionScanner(EmotionScanner):
    """复用船坞心情区域，按舰队扫描网格读取原始心情值。"""

    def __init__(self, grid_shape=(7, 3), excluded_positions=()):
        super().__init__()
        card_grids = ButtonGrid(
            origin=CARD_GRIDS.origin, delta=CARD_GRIDS.delta,
            button_shape=CARD_GRIDS.button_shape, grid_shape=grid_shape, name='CARD',
        )
        origin = CARD_EMOTION_GRIDS.origin - CARD_GRIDS.origin
        area = tuple(np.append(origin, origin + CARD_EMOTION_GRIDS.button_shape))
        self.grids = card_grids.crop(area=area, name='EMOTION')
        excluded = set(excluded_positions)
        self.ocr_model = FleetEmotionDigit(
            [button for x, y, button in self.grids.generate() if (x, y) not in excluded],
            letter=self.ocr_model.letter, threshold=self.ocr_model.threshold,
            alphabet='0123456789', name='FLEET_EMOTION_OCR',
        )

    def _scan(self, image):
        if server.server == 'jp':
            # 日服使用不同的数字区域和字色，沿用既有识别。
            return self.ocr_model.ocr(image)
        status_scanner = EmotionStatusScanner()
        number_offset = CARD_EMOTION_GRIDS.origin - CARD_GRIDS.origin
        status_offset = CARD_EMOTION_STATUS_GRIDS.origin - CARD_EMOTION_GRIDS.origin
        status_shape = CARD_EMOTION_STATUS_GRIDS.button_shape
        statuses, images = [], []
        for area in self.ocr_model.buttons:
            left, top = np.array(area[:2]) + status_offset
            status = status_scanner.get_emotion_status(crop(
                image, (left, top, left + status_shape[0], top + status_shape[1]),
            ))
            if status in ('red', 'yellow'):
                # 同时确认数字左侧和卡片右侧图标，避免把红色立绘当作零心情。
                x, y = np.array(area[:2]) - number_offset
                icon = crop(image, (x - 2, y + 29, x + 19, y + 51))
                color = EMOTION_RED if status == 'red' else EMOTION_YELLOW
                if not image_color_count(icon, color=color, count=300):
                    status = 'unknown'
            raw = crop(image, area)
            images.append(self.ocr_model.prepare_low_emotion(raw) if status == 'yellow' else raw)
            statuses.append(status)
        results = self.ocr_model.ocr(images, direct_ocr=True)
        results = results if isinstance(results, list) else [results]
        # Lua 心情配置：红色只对应0，黄色对应1–30；不截位或猜测失败的数字。
        for index, (value, status) in enumerate(zip(results, statuses)):
            if status == 'red':
                results[index] = 0
            elif status == 'yellow' and (value is None or not 1 <= value <= 30):
                results[index] = None
        logger.attr('舰队心情OCR', results)
        return results


class FleetManagementScanner:
    """扫描当前船坞页面，并按舰队归属聚合舰娘名称、等级与心情。"""
    def __init__(
        self,
        grid_shape: Tuple[int, int] = (7, 3),
        excluded_positions: Tuple[Tuple[int, int], ...] = (),
    ) -> None:
        self.fleet_scanner = FleetScanner(
            grid_shape=grid_shape,
            excluded_positions=excluded_positions,
        )
        self.name_scanner = FleetNameScanner(
            grid_shape=grid_shape,
            excluded_positions=excluded_positions,
        )
        self.level_scanner = LevelScanner(
            grid_shape=grid_shape,
            excluded_positions=excluded_positions,
        )
        self.emotion_scanner = FleetEmotionScanner(
            grid_shape=grid_shape,
            excluded_positions=excluded_positions,
        )

    def scan(self, image) -> Dict[int, List[Dict[str, Union[str, int, None]]]]:
        """返回按舰队编号分组的舰娘名称、等级与心情 OCR 结果。

        Args:
            image (np.ndarray): 船坞截图图像。

        Returns:
            dict: 键为舰队编号，值为包含 name、level 与 emotion 的字典列表。
                心情识别失败时 emotion 为 None，不影响名称与等级。
        """
        fleets = self.fleet_scanner.scan(image, output=False)
        names = self.name_scanner.scan(image, output=False)
        levels = self.level_scanner.scan(image, output=False)
        emotions = self.emotion_scanner.scan(image, output=False)
        result = defaultdict(list)
        for index, (fleet, name, level) in enumerate(zip(fleets, names, levels)):
            if fleet:
                emotion = emotions[index] if index < len(emotions) else None
                result[fleet].append({'name': name, 'level': level, 'emotion': emotion})
        return dict(result)


class StatusScanner(Scanner):
    """状态扫描器，通过模板匹配识别舰船的使用状态。

    状态类型：free(空闲)、battle(出击中)、commission(委托中)、
    in_hard_fleet(困难舰队)、in_event_fleet(活动舰队)。
    """
    def __init__(self) -> None:
        super().__init__()
        self._results = []
        self.grids = CARD_GRIDS
        self.value_list: List[str] = [
            'free',
            'battle',
            'commission',
            'in_hard_fleet',
            'in_event_fleet',
        ]
        self.templates = {
            TEMPLATE_IN_BATTLE: 'battle',
            TEMPLATE_IN_COMMISSION: 'commission',
            TEMPLATE_IN_HARD: 'in_hard_fleet',
            TEMPLATE_IN_EVENT_FLEET: 'in_event_fleet',
        }

    def _match(self, image) -> str:
        """通过模板匹配识别舰船状态。

        Args:
            image (np.ndarray): 卡片区域图像。

        Returns:
            str: 舰船状态 ('battle', 'commission', 'in_hard_fleet', 'in_event_fleet', 'free')。
        """
        for template, status in self.templates.items():
            if template.match(image, similarity=0.8):
                return status

        return 'free'

    def _scan(self, image) -> List:
        image_list = [crop(image, button.area) for button in self.grids.buttons]

        return [self._match(image) for image in image_list]

    def limit_value(self, value) -> str:
        return value if value in self.value_list else 'any'


class HashGenerator(Scanner):
    """哈希生成器，为每张船坞卡片生成 DHash 感知哈希。

    用于 DockScanner 跨页扫描时的去重判断和加载完成检测。
    """
    def __init__(self, length=8) -> None:
        super().__init__()
        self._results = []
        self.length = length
        self.grids = CARD_GRIDS

    def _scan(self, image) -> List:
        image_list = [crop(image, button.area) for button in self.grids.buttons]

        return [DHash(image, self.length) for image in image_list]

    def limit_value(self, value) -> Any:
        pass


class ShipScanner(Scanner):
    """舰船扫描器，用于扫描船坞页面中所有舰船的属性信息。

    必须在船坞初始页面使用（设置筛选器后不能有滚动操作），否则结果不可靠。
    如需跨页扫描，请使用 DockScanner。

    Args:
        rarity: 稀有度筛选，取值 'any'、'common'、'rare'、'elite'、'super_rare'，支持 str 或 list。
        level: 等级范围 (下限, 上限)，自动限制在 [1, 125]。
        emotion: 情绪范围 (下限, 上限)，自动限制在 [0, 150]。
        fleet: 舰队编号，0 表示不在任何编队，自动限制在 [0, 6]。
        status: 状态筛选，取值 'free'、'battle'、'commission'、'in_hard_fleet'、'in_event_fleet'。

    属性支持两个特殊值 False 和 None：

    使用 False:
        跳过该属性的扫描，结果中对应字段为 None。
        设置为 False 后只能通过 enable() 重新启用，
        disable() 的效果与设为 False 相同。

    使用 None:
        正常扫描该属性，但筛选时忽略该属性的限制。
        调用 set_limitation(property=...) 可重置限制（包括设为 None）。

    Examples:
        ShipScanner(rarity=False) 扫描时忽略稀有度，结果中 rarity 为 None。
    """
    def __init__(
        self,
        rarity: str = 'any',
        level: Tuple[int, int] = (1, 125),
        emotion: Tuple[int, int] = (0, 150),
        fleet: int = 0,
        status: str = 'any'
    ) -> None:
        super().__init__()
        self._results = []
        self.grids = CARD_GRIDS
        self.limitation: Dict[str, Union[str, int, Tuple[int, int]]] = {
            'level': (1, 125),
            'emotion': (0, 150),
            'rarity': 'any',
            'fleet': 0,
            'status': 'any',
        }

        # 每个舰船属性绑定一个独立的子扫描器
        self.sub_scanners: Dict[str, Scanner] = {
            'level': LevelScanner(),
            'emotion': EmotionScanner(),
            'rarity': RarityScanner(),
            'fleet': FleetScanner(),
            'status': StatusScanner(),
            'hash': HashGenerator(),
        }

        self.set_limitation(
            level=level, emotion=emotion, rarity=rarity, fleet=fleet, status=status)

    def _scan(self, image) -> List:
        for scanner in self.sub_scanners.values():
            scanner.scan(image, cached=True)

        candidates: List[Ship] = [
            Ship(
                level=level,
                emotion=emotion,
                rarity=rarity,
                fleet=fleet,
                status=status,
                button=button,
                hash_=hash_)
            for level, emotion, rarity, fleet, status, button, hash_ in
            zip(
                self.sub_scanners['level'].results,
                self.sub_scanners['emotion'].results,
                self.sub_scanners['rarity'].results,
                self.sub_scanners['fleet'].results,
                self.sub_scanners['status'].results,
                self.grids.buttons,
                self.sub_scanners['hash'].results)
        ]

        for scanner in self.sub_scanners.values():
            scanner.clear()

        return candidates

    def scan(self, image, cached=False, output=True) -> Union[List, None]:
        ships = super().scan(image, cached, output)
        if not cached:
            return [ship for ship in ships if ship.satisfy_limitation(self.limitation)]

    def move(self, vector) -> None:
        """移动网格坐标，同步更新所有子扫描器和自身的网格位置。"""
        for scanner in self.sub_scanners.values():
            scanner.move(vector)

        super().move(vector)

    def limit_value(self, key, value) -> None:
        if value is None:
            self.limitation[key] = None
        elif isinstance(value, tuple):
            lower, upper = value
            lower = self.sub_scanners[key].limit_value(lower)
            upper = self.sub_scanners[key].limit_value(upper)
            self.limitation[key] = (lower, upper)
        elif isinstance(value, list):
            self.limitation[key] = [self.sub_scanners[key].limit_value(v) for v in value]
        else:
            self.limitation[key] = self.sub_scanners[key].limit_value(value)

    def enable(self, *args) -> None:
        """启用指定属性的子扫描器。

        支持的属性：'level'、'emotion'、'rarity'、'fleet'、'status'。
        """
        for name, scanner in self.sub_scanners.items():
            if name in args:
                scanner.enable()

    def disable(self, *args) -> None:
        """禁用指定属性的子扫描器。

        支持的属性：'level'、'emotion'、'rarity'、'fleet'、'status'。
        """
        for name, scanner in self.sub_scanners.items():
            if name in args:
                scanner.disable()

    def set_limitation(self, **kwargs):
        """设置舰船筛选条件。

        Args:
            rarity: 稀有度，取值 'any'、'common'、'rare'、'elite'、'super_rare'。
            level: 等级范围 (下限, 上限)，自动限制在 [1, 125]。
            emotion: 情绪范围 (下限, 上限)，自动限制在 [0, 150]。
            fleet: 舰队编号，0 表示不在任何编队，自动限制在 [0, 6]。
            status: 状态，取值 'free'、'battle'、'commission'、'in_hard_fleet'、'in_event_fleet'。
        """
        for attr in self.limitation.keys():
            value = kwargs.get(attr, self.limitation[attr])
            self.limit_value(key=attr, value=value)
            if value is False:
                self.sub_scanners[attr].disable()

        logger.info(f'筛选条件已设置为 {self.limitation}')


class DockScanner(ShipScanner):
    """船坞扫描器，支持跨页扫描。

    与 ShipScanner 相同，必须从船坞初始页面开始扫描。
    扫描过程会自动滚动船坞，扫描完成后自动停止。
    """
    SCAN_ZONES: Dict[str, Tuple[int, int, int, int]] = {
        'dock': (93, 55, 1219, 719),
    }
    def __init__(self, zone: str = 'dock', test_name: str = '') -> None:
        self._results = []
        self.scan_zone: Tuple[int, int, int, int] = self.SCAN_ZONES[zone]
        self.zone_top: int = self.scan_zone[1]
        self.zone_height: int = self.scan_zone[3] - self.scan_zone[1]
        self.grids_top: int = 76
        # 用于重新定位和滚动计算
        self.mean_color_set = deque(maxlen=2)
        self.moving_distance: int = 0
        self.bound = []
        # 用于扫描稳定性判断
        self._stable: bool = False
        self._no_change: int = 0
        self.last_results = []
        self.retry: int = 0

        self.scanner = ShipScanner(emotion=False, fleet=False, status=False)

        # 以下为调试信息相关
        self.save_debug_info = False
        self.debug_folder = f'./log/dock_scan_test/{test_name}_{int(time.time()*1000):x}'
        if self.save_debug_info:
            if not os.path.exists('./log/dock_scan_test'):
                os.mkdir('./log/dock_scan_test')
            if not os.path.exists(self.debug_folder):
                os.mkdir(self.debug_folder)
        self.debug_info = {
            'time' : 0,
            'ship_count' : 0,
            'dock_size' : 0,
            'ocr_mistake' : 0,
            'reposition_retry' : 0,
        }
        self.ocr_mistake_image = []
        self.extend_log = []
        self.moving_distance_log = []

    def limit_value(self, value) -> Any:
        pass

    @property
    def stable(self) -> bool:
        if self._stable:
            self._stable = False
            return True
        else:
            return False

    @property
    def mean_color(self):
        return self.mean_color_set[-1] if self.mean_color_set else None

    @mean_color.setter
    def mean_color(self, value):
        self.mean_color_set.append(value)

    def no_change(self) -> bool:
        return self._no_change > 3

    def _find_bound(self, image) -> List[int]:
        """粗略定位舰船卡片间的空白行位置。

        空白行的标准差会出现明显波谷，通过定位波谷位置即可获得
        空白行的大致位置。精度不高，但只需其中心点即可。

        Args:
            image (np.ndarray): 截图图像。

        Returns:
            list[int]: 空白行的 Y 坐标列表。
        """
        image = crop(image, self.scan_zone)
        image = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        std = np.std(image, axis=1)
        move_avg = np.convolve(std, np.ones((5, )) / 5, mode='valid')
        gap_seq = list(np.nonzero(move_avg < 20)[0]) + [1000]

        bound = []
        start = 0
        for i in range(len(gap_seq) - 1):
            if gap_seq[i + 1] - gap_seq[i] > 50 and i + 1 - start > 10:
                bound.append(np.mean(gap_seq[start : i + 1]).astype(int))
                start = i + 1
        if len(bound) > 1:
            # 最后一行不可靠，限制其与上一行的最大间距
            bound[-1] = min(bound[-2] + 225, bound[-1])

        return bound

    def reset_position(self) -> None:
        """重置网格位置至初始顶部，并同步更新内部扫描器。"""
        offset = 76 - self.grids_top
        self.grids_top += offset
        self.scanner.move((0, offset))
        self.mean_color_set.append(self.mean_color_set[0])

    def reposition(self, image, bound) -> None:
        """精确调整网格位置。

        从 bound 给出的空白行中心点向下搜索，第一个颜色与 mean_color
        差异较大的行即为新 CARD_GRIDS 的顶部位置。

        Args:
            image (np.ndarray): 截图图像。
            bound (list[int]): 空白行位置列表。
        """
        scan_image = crop(image, self.scan_zone)
        if self.mean_color is not None:
            for y in range(0, 20):
                if not color_similar(np.mean(scan_image[bound[0] + y], axis=0), self.mean_color, 60):
                    break
            offset = y + self.zone_top + bound[0] + 1 - self.grids_top
            self.grids_top += offset
            self.scanner.move((0, offset))

        self.mean_color = np.mean(scan_image[bound[-1]], axis=0)

    def _remove_duplicate(self, results) -> int:
        """去除重复扫描结果，返回新增条目数。

        两种重复情况：
            整页重复：新结果与上一次完全相同。
            半页重复：新结果前半部分与上次后半部分相同。
        两种情况下，len(results) < 14 表示已到达底部。

        Args:
            results (list[Ship]): 本次扫描到的舰船列表。

        Returns:
            int: 新增的舰船数量。
        """
        if self._results:
            if all([old.hash_ == new.hash_ for new, old in zip(results, self._results[-len(results):])]):
                self._no_change += 999 if len(results) < 14 else 1
                return 0
            elif all([old.hash_ == new.hash_ for new, old in zip(results[:7], self._results[-7:])]):
                self._results.extend(results[7-len(results):])
                self._no_change = 999 if len(results) < 14 else 0
                return len(results)-7

        self._no_change = 0
        self._results.extend(results)
        return len(results)

    def ensure_in_dock(self, main) -> None:
        if main.appear(SHIP_DETAIL_CHECK, offset=(30, 30)):
            main.ui_back(DOCK_CHECK)

    def _scan(self, image) -> None:
        bound = self._find_bound(image)
        if len(bound) == 1:
            # 没有舰船出现，页面已稳定
            self._stable = True
            return
        elif len(bound) == 2:
            if self.bound != bound:
                self._stable = False
                self.bound = bound
                return
        else:
            self.bound.clear()

        self.moving_distance = bound[-1] - (self.zone_height - 204 * 2 - 23 * 3) / 2 * 1.5
        self.moving_distance_log.append(self.moving_distance)
        self.reposition(image, bound)
        results = self.scanner.scan(image, cached=False, output=False)
        if not results:
            self.retry += 1
            self.debug_info['reposition_retry'] += 1
            logger.info(f'[退役-扫描] 未检测到舰船，重置位置。重试第 {self.retry} 次')
            self.reset_position()
            self.reposition(image, bound)
            results = self.scanner.scan(image, cached=False, output=False)
            if self.retry > 3:
                self.moving_distance = random_normal_distribution_int(10, 20)
                self.retry = 0
        else:
            self.retry = 0

        if all([old.hash_ == new.hash_ for new, old in zip(results, self.last_results)]):
            self._stable = True
            inc = self._remove_duplicate(results)
            if inc:
                level = [ship.level for ship in results]
                self.extend_log.append((inc, self.grids_top, level, cv2.cvtColor(image, cv2.COLOR_BGR2RGB)))

                level = [ship.level for ship in results]
                greater_equal = [level[i-1] >= level[i] for i in range(1, len(level))]
                in_order = all(x == greater_equal[0] for x in greater_equal)
                if not in_order:
                    interrupt = np.where(np.array(greater_equal)==False)[0].tolist()
                    values = [level[i] for i in interrupt]
                    level_info = '_'.join([f'{p,v}' for p,v in zip(interrupt,values)])
                    self.ocr_mistake_image.append((
                        f"{self.debug_info['ocr_mistake']}_{self.grids_top}_{level_info}.png", cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                    ))
                    self.debug_info['ocr_mistake'] += 1

        self.last_results = results

    def multi_scan(self, main) -> None:
        """执行船坞多页扫描，自动滚动并收集所有舰船信息。

        扫描原理示意：
            □ | □ | □                          --------- (*)
            ---------                          ■ | □ | □
            □ | □ | □       --- 滚动 --->      ---------
            --------- (*)                      □ | □ | □
            ■ | □ | □                          ---------
        □ 和 ■ 为舰船，| 和 - 为舰船间的空白间隔。
        需要计算 (*) 移动的距离来检测滚动。

        舰船间空白区域的颜色变化很小，将图像灰度化后用 np.std
        过滤即可获得空白行的位置。

        Args:
            main: 具有截图和操作能力的宿主任务实例。
        """
        from module.retire.enhancement import OCR_DOCK_AMOUNT
        self.debug_info['dock_size'], _, _ = OCR_DOCK_AMOUNT.ocr(main.device.image)

        if DOCK_SCROLL.appear(main):
            # 预先滚动到底部再回到顶部，可部分预加载舰船图像，
            # 降低扫描过程中卡住的可能性
            DOCK_SCROLL.set_bottom(main)
            DOCK_SCROLL.set_top(main)

        start_time = time.time()
        while True:
            while not self.stable:
                main.device.screenshot()
                self.ensure_in_dock(main)
                self._scan(main.device.image)

            click_zone_index = random_normal_distribution_int(0, 6)
            start = random_rectangle_point((
                240 + click_zone_index * 165, 555, 250 + click_zone_index * 165, 719
            ))
            end = (start[0], start[1] - self.moving_distance)
            sharp_end = (end[0] - 165, end[1])
            main.device.swipe(start, end)
            main.device.click_record.pop()
            main.device.swipe(end, sharp_end)
            main.device.click_record.pop()

            if not DOCK_SCROLL.appear(main) or (DOCK_SCROLL.at_bottom(main) and self.no_change()):
                break
        end_time = time.time()
        self.debug_info['time'] = end_time - start_time
        self.debug_info['ship_count'] = len(self._results)

        if self.save_debug_info:
            # 保存哈希相似度数据
            hashs = [ship.hash_ for ship in self.results]
            sims = []
            for i in range(len(hashs)):
                for j in range(i+1, len(hashs)):
                    sims.append(DHash.distance(hashs[i],hashs[j]))
            np.save(f'{self.debug_folder}/{len(sims)}.npy', np.array(sims))
            # 保存 OCR 识别错误的图像
            for name, image in self.ocr_mistake_image:
                cv2.imwrite(f'{self.debug_folder}/{name}.png', image)
            # 保存去重异常的图像
            self.extend_log.append((0, None))
            for i in range(len(self.extend_log) - 1):
                cnt, top, level, image = self.extend_log[i]
                if cnt != 14 and cnt != 7 and self.extend_log[i+1][0] != 0:
                    cv2.imwrite(f'{self.debug_folder}/len={cnt}_top={top}_id={i}.png', image)
                    self.debug_info[f'len={cnt}_top={top}_id={i}'] = level
            # 保存调试信息摘要
            self.debug_info['moving_mean'] = np.mean(self.moving_distance_log)
            with open(f'{self.debug_folder}/debug_info.txt', 'w', encoding='utf-8') as f:
                for k,v in self.debug_info.items():
                    f.write(f'{k} = {v}\n')

            logger.info(f'[退役-扫描] 调试信息已保存到 {self.debug_folder}')

    def scan(self, image, cached=False, output=True) -> Union[List, None]:
        """请使用 multi_scan() 代替。"""
        pass

    def scan_one_fleet(self, fleet: int = None) -> List[Ship]:
        """扫描指定舰队中的所有舰船。

        Args:
            fleet: 舰队编号，未指定时使用 self.fleet。

        Returns:
            list[Ship]: 舰船列表。
        """
        pass

    def scan_whole_dock(self) -> List[Ship]:
        """扫描整个船坞。"""
        pass
