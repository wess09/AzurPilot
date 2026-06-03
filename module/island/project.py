from datetime import datetime, timedelta
import cv2
import re
import numpy as np
from scipy import signal
import os
import time

import module.config.server as server

from module.base.button import Button, ButtonGrid
from module.base.timer import Timer
from module.base.utils import color_similarity_2d, crop, random_rectangle_vector, rgb2gray, lower_template_match_similarity
from module.config.deep import deep_get, deep_values
from module.island.assets import *
from module.island.project_data import *
from module.island.ui import IslandUI
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.ocr.ocr import Duration, Ocr
from module.ocr.al_ocr import AlOcr
from module.ui.switch import Switch


ROLE_SORTING = Switch('Role_sorting')
ROLE_SORTING.add_state('Ascending', check_button=ROLE_SORT_ASC, click_button=ROLE_SORTING_CLICK)
ROLE_SORTING.add_state('Descending', check_button=ROLE_SORT_DESC, click_button=ROLE_SORTING_CLICK)


class ProjectNameOcr(Ocr):
    def after_process(self, result):
        result = super().after_process(result)
        if server.server == 'cn':
            result = result.replace('主', '丰')
            result = re.sub(r'[^\u4e00-\u9fff]', '', result)
        elif server.server == 'en':
            result =  re.sub(r"[\s'-]+", "", result).lower()
        return result


class IslandProject:
    # 是否成功解析项目
    valid: bool
    # OCR 识别结果（项目名称）
    name: str
    # 项目工作场所 ID
    id: int
    # 工作场所最大槽位数
    max_slot: int
    # 工作场所可用槽位数
    slot: int
    # 所有可用槽位的按钮
    slot_buttons: ButtonGrid

    def __init__(self, image, image_gray, button):
        """
        初始化岛屿项目对象，解析项目信息。

        Args:
            image: 原始截图
            image_gray: 灰度截图
            button: 项目模板匹配到的按钮
        """
        self.image = image
        self.image_gray = image_gray
        self.button = button
        self.x1, self.y1, self.x2, self.y2 = button.area
        self.valid = True
        self.project_parse()

    def project_parse(self):
        # 无效项目判断
        if self.y2 + 110 >= 653:
            self.valid = False
            return

        # 检查是否锁定
        area = (self.x1 - 228, self.y1 + 57, self.x1 - 195, self.y1 + 95)
        image = crop(self.image_gray, area, copy=False)
        if TEMPLATE_PROJECT_LOCKED.match(image):
            self.valid = False
            return

        # OCR 识别项目名称
        dx = {'cn': 326, 'en': 137}[server.server]
        dy = {'cn': 0, 'en': 2}[server.server]
        area = (self.x1 - 446, self.y1, self.x1 - dx, self.y2 + dy)
        button = Button(area=area, color=(), button=area, name='PROJECT_NAME')
        ocr = ProjectNameOcr(button, lang='cnocr')
        self.name = ocr.ocr(self.image)
        if not self.name:
            self.valid = False
            return

        # 根据名称查找项目 ID
        keys = list(name_to_slot.keys())
        if self.name in keys:
            self.id = keys.index(self.name) + 1
        else:
            self.valid = False
            return

        # 获取最大槽位数
        self.max_slot = name_to_slot.get(self.name, 2)

        # 计算可用槽位数
        area = (self.x1 - 383, self.y1 + 60, self.x1 - 39, self.y1 + 118)
        image = crop(self.image_gray, area, copy=False)
        locked = TEMPLATE_SLOT_LOCKED.match_multi(image)
        self.slot = self.max_slot - len(locked)
        if not self.slot:
            self.valid = False
            return

        # 生成槽位按钮网格
        self.slot_buttons = ButtonGrid(origin=(self.x1 - 383, self.y1 + 60), delta=(95, 0),
                                       button_shape=(58, 58), grid_shape=(self.slot, 1), name='PROJECT_SLOT')

    def __eq__(self, other):
        """
        比较两个岛屿项目是否相同。

        Args:
            other (IslandProject): 另一个项目对象

        Returns:
            bool: 是否相等
        """
        if not isinstance(other, IslandProject):
            return False
        if not self.valid or not other.valid:
            return False
        if self.name != other.name:
            return False
        if self.id != other.id:
            return False

        return True

    def __str__(self):
        return self.name


class IslandProduct:
    # 产品生产持续时间
    duration: timedelta
    # 是否成功解析产品时长
    valid: bool

    def __init__(self, image, offset=None, new=False):
        if new:
            button = OCR_PRODUCTION_TIME
            if offset:
                button = OCR_PRODUCTION_TIME.move(offset)
            ocr = Duration(button, lang='cnocr', name='OCR_PRODUCTION_TIME')
            self.duration = ocr.ocr(image)
        else:
            ocr = Duration(OCR_PRODUCTION_TIME_REMAIN, name='OCR_PRODUCTION_TIME_REMAIN')
            self.duration = ocr.ocr(image)
        self.valid = True

        if not self.duration.total_seconds():
            self.valid = False

        self.create_time = datetime.now()

    @property
    def finish_time(self):
        if self.valid:
            return (self.create_time + self.duration).replace(microsecond=0)
        else:
            return None

    def __eq__(self, other):
        """
        比较两个产品是否相同（基于时长阈值）。

        Args:
            other (IslandProduct): 另一个产品对象

        Returns:
            bool: 是否相等
        """
        if not isinstance(other, IslandProduct):
            return False
        threshold = timedelta(seconds=120)
        if not self.valid or not other.valid:
            return False
        if (other.duration < self.duration - threshold) or (other.duration > self.duration + threshold):
            return False

        return True


class ItemNameOcr(Ocr):
    def after_process(self, result):
        result = super().after_process(result)
        if server.server == 'cn':
            result = result.replace('蛮', '蜜').replace('汗', '汁').replace('纠', '组') \
                .replace('离', '禽').replace('莱', '菜').replace('内', '肉') \
                .replace('克', '苋').replace('蛟', '鲛')
            result = re.sub(r'[^\u4e00-\u9fff]', '', result)
            if '冰咖' in result:
                result = '冰咖啡'
            elif '莓果香橙' in result:
                result = '莓果香橙甜点组'
            elif '莉精油' in result:
                result = '茉莉精油'
            elif result == '胡萝下':
                result = '胡萝卜'
            elif result == '草莓奶缘':
                result = '草莓奶绿'
            elif result == '红鱼':
                result = '红鲷鱼'
            elif result == '黑鱼':
                result = '黑鲷鱼'
        elif server.server == 'en':
            result = re.sub(r"[\s'-]+", "", result)
            result = result.lower()
        return result


class ProductItem:
    PRODUCT_ROW_NAME_TO_CENTER_Y = 36
    PRODUCT_ROW_HALF_HEIGHT = 65
    PRODUCT_SELECTED_COLOR = (57, 189, 255)
    PRODUCT_SELECTED_THRESHOLD = 221
    PRODUCT_SELECTED_BORDER_WIDTH = 14
    PRODUCT_SELECTED_BORDER_COUNT = 160
    # OCR 识别结果（物品名称）
    name: str
    # 是否成功解析物品名称
    valid: bool
    # 当前物品的点击按钮
    button: Button
    # 当前页面所有物品的按钮网格
    item_buttons: ButtonGrid

    @staticmethod
    def _normalize_product_text(text):
        text = str(text or '').lower()
        return re.sub(r'[\W_]+', '', text)

    @classmethod
    def resolve_product_name(cls, detected, known_names):
        normalized = cls._normalize_product_text(detected)
        if not normalized:
            return None
        for name in known_names:
            product = cls._normalize_product_text(name)
            if normalized == product:
                return name
            if len(product) >= 2 and product in normalized:
                return name
        return None

    @classmethod
    def empty(cls, image, parent_project_id):
        item = cls.__new__(cls)
        item.image = image
        item.y = []
        item.valid = True
        item.name = None
        item.button = None
        item.parent_project_id = parent_project_id
        item.items = []
        item.item_buttons = None
        item.is_fallback = False
        return item

    @classmethod
    def row_area_from_name_center(cls, cy):
        left, top, right, bottom = ISLAND_PRODUCT_ITEMS.area
        center = cy + cls.PRODUCT_ROW_NAME_TO_CENTER_Y
        y1 = int(max(top, center - cls.PRODUCT_ROW_HALF_HEIGHT))
        y2 = int(min(bottom, center + cls.PRODUCT_ROW_HALF_HEIGHT))
        return left + 20, y1, right - 20, y2

    @classmethod
    def row_is_selected(cls, image, area):
        left, y1, right, y2 = area
        border = cls.PRODUCT_SELECTED_BORDER_WIDTH
        top = crop(image, (left - 20, y1, right + 20, min(y1 + border, y2)), copy=False)
        bottom = crop(image, (left - 20, max(y1, y2 - border), right + 20, y2), copy=False)
        top_similarity = color_similarity_2d(top, color=cls.PRODUCT_SELECTED_COLOR)
        bottom_similarity = color_similarity_2d(bottom, color=cls.PRODUCT_SELECTED_COLOR)
        selected_pixels = (
            np.count_nonzero(top_similarity > cls.PRODUCT_SELECTED_THRESHOLD)
            + np.count_nonzero(bottom_similarity > cls.PRODUCT_SELECTED_THRESHOLD)
        )
        return selected_pixels >= cls.PRODUCT_SELECTED_BORDER_COUNT

    @classmethod
    def from_ocr_results(cls, image, parent_project_id, product_order):
        item = cls.empty(image, parent_project_id)
        item.is_fallback = True
        detector = AlOcr(name='zhcn' if server.server == 'cn' else 'en')
        try:
            det_results = detector.det(image)
        except Exception as e:
            logger.warning(f'Product OCR fallback failed: {e}')
            det_results = []

        left, top, right, bottom = ISLAND_PRODUCT_ITEMS.area
        seen = set()
        for txt, box, score in det_results:
            xs = [point[0] for point in box]
            ys = [point[1] for point in box]
            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)
            if not (left <= cx <= right and top <= cy <= bottom):
                continue
            resolved = cls.resolve_product_name(txt, product_order)
            if not resolved:
                continue
            normalized = cls._normalize_product_text(resolved)
            if normalized in seen:
                continue
            seen.add(normalized)
            area = cls.row_area_from_name_center(cy)
            _, y1, _, y2 = area
            row = cls.empty(image, parent_project_id)
            row.y = (y1, y2)
            row.name = resolved
            row.button = Button(area=area, color=(), button=area, name=f'ISLAND_ITEM_{resolved}')
            if cls.row_is_selected(image, area):
                item.name = resolved
            item.items.append(row)

        if item.items:
            logger.info(f'Product OCR fallback rows: {[row.name for row in item.items]}, selected={item.name}')
        return item

    def __init__(self, image, y, parent_project_id, get_button=True):
        """
        初始化产品物品对象。

        Args:
            image: 截图图像
            y (int): 物品的纵向坐标
            get_button (bool): 是否解析当前页面的其他物品
        """
        self.image = image
        self.y = y
        self.valid = True
        self.name = None
        self.button = None
        self.items = []
        self.parent_project_id = parent_project_id
        self.parse_item(get_button=get_button)

    def parse_item(self, get_button):
        if len(self.y) < 2:
            self.valid = False
            return

        y1, y2 = self.y

        # OCR 识别物品名称
        if get_button:
            self.ocr_name(y1, y2)

        # 生成物品按钮
        x1, x2 = ISLAND_PRODUCT_ITEMS.area[0] + 20, ISLAND_PRODUCT_ITEMS.area[2] - 20
        area = (x1, y1, x2, y2)
        self.button = Button(area=area, color=(), button=area, name='ISLAND_ITEM')
        if get_button:
            delta = 149
            up, down = self.grid_num(delta, y1, y2)
            shape_y = up + down + 1
            origin_y = y1 - up * delta
            self.item_buttons = ButtonGrid(origin=(x1, origin_y), delta=(0, delta),
                                           button_shape=(x2 - x1, y2 - y1),
                                           grid_shape=(1, shape_y), name='ITEMS')
            self.items = [ProductItem(self.image, (item.area[1], item.area[3]), self.parent_project_id, get_button=False)
                          for item in self.item_buttons.buttons]
        else:
            self.ocr_name(y1, y2)


    @staticmethod
    def grid_num(delta, y1, y2):
        """
        计算当前网格上方和下方的网格数量。

        Args:
            delta (int): 网格间距
            y1 (int): 网格顶部坐标
            y2 (int): 网格底部坐标

        Returns:
            tuple(int, int): (上方网格数, 下方网格数)
        """
        up = 0
        down = 0
        while y1 - delta > ISLAND_PRODUCT_ITEMS.area[1]:
            up += 1
            y1 -= delta
        while y2 + delta < ISLAND_PRODUCT_ITEMS.area[3]:
            down += 1
            y2 += delta
        return up, down

    def ocr_name(self, y1, y2):
        """
        对指定区域进行 OCR 识别物品名称。

        Args:
            y1 (int): 区域顶部坐标
            y2 (int): 区域底部坐标
        """
        area = (300, y1 + 14, 440, y2 - 84)
        button = Button(area=area, color=(), button=area, name='ITEM_NAME')
        ocr = ItemNameOcr(button, lang='cnocr', letter=(70, 70, 70))
        self.name = ocr.ocr(self.image)
        if server.server == 'cn' and (not self.name or self.name not in deep_values(items_data, depth=2)):
            self.valid = False
        elif server.server == 'en':
            self.valid = False
            if not self.name:
                return
            for value in list(items_data[self.parent_project_id].values()):
                can_scroll = len(value) > 13
                vmatcher = re.sub(r"[\s'-]+", "", value).lower()
                if self.name == vmatcher:
                    logger.info(f'Product with valid name: {self.name} (exact matched {value})')
                    self.name = value
                    self.valid = True
                    break
                elif self.name[1:-1] in vmatcher and (len(self.name) > 12 and can_scroll):
                    logger.info(f'Product with valid name: {self.name} (scroll matched {value})')
                    self.name = value
                    self.valid = True
                    break
            if not self.valid:
                logger.info(f'Product with invalid name: {self.name}')

    def __eq__(self, other):
        """
        比较两个产品物品是否相同。

        Args:
            other (ProductItem): 另一个物品对象

        Returns:
            bool: 是否相等
        """
        if not isinstance(other, ProductItem):
            return False
        if not self.valid or not other.valid:
            return False
        if self.name != other.name:
            return False

        return True


class IslandProjectRun(IslandUI):
    DEBUG_ISLAND_PROJECT = False
    LIST_SPLIT = re.compile(r'[,，;；/、\n]+')
    RANCH_PROJECT_ID = 2
    PRODUCT_CURSOR_PATH = 'Island.Storage.Storage.ProductCursor'
    ROLE_CARD_ORIGIN = (58, 140)
    ROLE_CARD_DELTA = (140, 181)
    ROLE_CARD_SIZE = (120, 160)
    ROLE_CARD_GRID = (6, 2)
    ROLE_CARD_NAME_OFFSET = (-4, 103, 120, 136)
    ROLE_CARD_STAMINA_OFFSET = (2, 130, 92, 150)
    ROLE_DETAIL_NAME_AREA = (940, 96, 1150, 132)
    project = SelectedGrids([])
    projects_dirty = False
    total = SelectedGrids([])
    character: str
    _island_product_cursor: dict
    _island_product_cursor_dirty: bool

    @classmethod
    def parse_config_list(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in cls.LIST_SPLIT.split(value) if part.strip()]
        if isinstance(value, (list, tuple, set)):
            out = []
            for item in value:
                out.extend(cls.parse_config_list(item))
            return out
        return [value]

    @classmethod
    def option_is_empty(cls, option):
        if option is None or option == 0:
            return True
        if isinstance(option, str):
            option = option.strip()
            return not option or option == '0' or option == '不生产'
        return False

    @staticmethod
    def normalize_character_text(text):
        text = str(text or '').casefold()
        return re.sub(r'[\W_]+', '', text)

    @classmethod
    def resolve_character_key(cls, character):
        text = str(character or '').strip()
        if not text:
            return None
        normalized = cls.normalize_character_text(text)
        if not normalized:
            return None

        for key, names in CHARACTER_NAME_MAP.items():
            if normalized == cls.normalize_character_text(key):
                return key
            for name in names.values():
                if normalized == cls.normalize_character_text(name):
                    return key
        return text

    @classmethod
    def parse_character_candidates(cls, value):
        candidates = []
        seen = set()
        for item in cls.parse_config_list(value):
            character = cls.resolve_character_key(item)
            if not character or character in seen:
                continue
            seen.add(character)
            candidates.append(character)
        return candidates

    @classmethod
    def character_target_names(cls, character):
        names = [character]
        names.extend(CHARACTER_NAME_MAP.get(character, {}).values())
        out = []
        seen = set()
        for name in names:
            normalized = cls.normalize_character_text(name)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            out.append(normalized)
        return out

    @classmethod
    def character_name_match(cls, detected, character):
        detected = cls.normalize_character_text(detected)
        if not detected:
            return False
        targets = cls.character_target_names(character)
        if detected in targets:
            return True
        for target in targets:
            if len(target) >= 3 and len(detected) >= 3 and (target in detected or detected in target):
                return True
        return False

    @classmethod
    def character_detail_name_match(cls, detected, character):
        detected = cls.normalize_character_text(detected)
        if not detected:
            return False
        for target in cls.character_target_names(character):
            if detected == target or detected.startswith(target):
                return True
        return False

    @staticmethod
    def readable_character_name(character):
        return CHARACTER_NAME_MAP.get(character, {}).get(
            server.server,
            CHARACTER_NAME_MAP.get(character, {}).get('cn', character),
        )

    @staticmethod
    def product_cursor_key(project_id, slot):
        return f'{project_id}:{slot}'

    def reset_island_storage_cache(self):
        cursor = self.config.cross_get(keys=self.PRODUCT_CURSOR_PATH, default={})
        if not isinstance(cursor, dict):
            cursor = {}
        self._island_product_cursor = dict(cursor)
        self._island_product_cursor_dirty = False

    @staticmethod
    def product_option_signature(candidates):
        return [str(option) for option in candidates]

    def get_product_cursor(self, project_id, slot, signature=None):
        key = self.product_cursor_key(project_id, slot)
        record = self._island_product_cursor.get(key, 0)
        if isinstance(record, dict):
            if signature is not None and record.get('signature') != signature:
                logger.info(f'Product list changed for {key}, reset cursor')
                return 0
            record = record.get('cursor', 0)
        elif signature is not None:
            logger.info(f'Product cursor for {key} has no signature, reset cursor')
            return 0

        try:
            cursor = int(record)
        except (TypeError, ValueError):
            cursor = 0
        return max(cursor, 0)

    def advance_product_cursor(self, option_info):
        if not option_info or not option_info['rotates']:
            return
        self._island_product_cursor[option_info['cursor_key']] = {
            'cursor': option_info['cursor_after'],
            'signature': option_info.get('signature', self.product_option_signature(option_info['candidates'])),
        }
        self._island_product_cursor_dirty = True

    def save_island_storage(self):
        if not self._island_product_cursor_dirty:
            return
        self.config.cross_set(keys=self.PRODUCT_CURSOR_PATH, value=self._island_product_cursor)
        self._island_product_cursor_dirty = False

    @staticmethod
    def resolve_product_option(project_id, option):
        if isinstance(option, int):
            return deep_get(items_data, [project_id, option])
        if isinstance(option, str):
            return option.strip()
        return option

    @staticmethod
    def dedupe_options(options):
        out = []
        seen = set()
        for option in options:
            key = str(option)
            if key in seen:
                continue
            seen.add(key)
            out.append(option)
        return out

    @staticmethod
    def product_candidate_sequence(option_info):
        candidates = option_info['candidates']
        if not option_info['rotates']:
            return [option_info]

        cursor_before = option_info['cursor_before']
        start = cursor_before % len(candidates)
        sequence = []
        for offset in range(len(candidates)):
            index = (start + offset) % len(candidates)
            current = dict(option_info)
            current['option'] = candidates[index]
            current['cursor_after'] = cursor_before + offset + 1
            current['candidate_index'] = index
            sequence.append(current)
        return sequence

    def project_detect(self, image):
        """
        从截图中检测所有岛屿项目。

        Args:
            image (np.ndarray): 截图图像

        Returns:
            SelectedGrids: 有效项目列表
        """
        image_gray = rgb2gray(image)
        projects = SelectedGrids([IslandProject(image, image_gray, button)
                                  for button in TEMPLATE_PROJECT.match_multi(image_gray)])
        return projects.select(valid=True)

    def ensure_project(self, name, trial=7, skip_first_screenshot=True):
        """
        确保指定项目出现在当前页面，通过滚动查找。

        Args:
            name (str|IslandProject): 需要确保的项目名称
            trial (int): 重试次数
            skip_first_screenshot (bool): 是否跳过首次截图
        """
        logger.hr('Project ensure')
        if isinstance(name, IslandProject):
            name = name.name
        for _ in range(trial):
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            projects = self.project_detect(self.device.image)
            if not projects:
                continue
            if name in projects.get('name'):
                logger.info(f'Ensured project: {name}')
                break

            keys = list(name_to_slot.keys())
            if name in keys:
                project_id = keys.index(name) + 1
                projects_id = projects.get('id')
                if project_id > projects_id[0]:
                    self.drag_page((0, -500), ISLAND_PROJECT_SWIPE.area, 0.6)
                else:
                    self.drag_page((0, 500), ISLAND_PROJECT_SWIPE.area, 0.6)
                self.projects_dirty = True
                continue
            else:
                logger.warning(f'Wrong project name {name}, skip ensuring')
                break

    def drag_page(self, vector, box, sleep=0.5):
        """
        拖拽管理页面。

        Args:
            vector (tuple): 拖拽方向向量
            box (tuple): 拖拽区域边界框
            sleep (float): 拖拽后等待时间
        """
        p1, p2 = random_rectangle_vector(vector, box=box, random_range=(0, -5, 0, 5))
        self.device.drag(p1, p2, segments=2, shake=(0, 25), point_random=(0, 0, 0, 0), shake_random=(0, -5, 0, 5))
        self.device.sleep(sleep)

    def is_in_enter_page(self):
        return self.image_color_count(ROLE_SELECT_TITLE_AREA, color=(57, 189, 255), threshold=221, count=8000)

    def project_receive(self, button):
        """
        领取项目奖励并进入角色选择页面。

        Args:
            button (Button): 项目按钮

        Returns:
            bool: 是否成功领取
        """
        self.device.click_record_clear()
        self.interval_clear([ISLAND_MANAGEMENT_CHECK, PROJECT_COMPLETE,
                             GET_ITEMS_ISLAND, ROLE_SELECT_ENTER])
        success = False
        click_timer = Timer(5, count=10).start()
        _stuck_get_items_count = 0
        for _ in self.loop():
            # UI 额外处理
            if self.island_in_management(interval=5):
                self.device.click(button)
                self.device.sleep(0.1)
                click_timer.reset()
                success = False
                continue

            if self.appear_then_click(ISLAND_MANAGEMENT, offset=(20, 20), interval=2):
                click_timer.reset()
                continue

            if self.handle_info_bar():
                click_timer.reset()
                continue

            # 进入角色选择页面
            if self.is_in_enter_page() and \
                    self.appear_then_click(ROLE_SELECT_ENTER, threshold=10, interval=2):
                success = True
                _stuck_get_items_count = 0
                self.interval_clear(GET_ITEMS_ISLAND)
                click_timer.reset()
                continue

            if self.appear_then_click(PROJECT_COMPLETE, offset=(20, 20), interval=1):
                success = True
                _stuck_get_items_count = 0
                self.interval_clear(GET_ITEMS_ISLAND)
                self.interval_reset(ROLE_SELECT_ENTER)
                click_timer.reset()
                continue

            if self.handle_get_items():
                _stuck_get_items_count = 0
                self.interval_clear(ROLE_SELECT_ENTER)
                click_timer.reset()
                continue

            # 处理岛屿升级弹窗
            if click_timer.reached():
                _stuck_get_items_count += 1
                if _stuck_get_items_count >= 3:
                    break
                self.device.click(GET_ITEMS_ISLAND)
                self.device.sleep(0.3)
                click_timer.reset()
                continue

            # 结束条件
            if self.appear(ROLE_SELECT_CONFIRM, offset=(20, 20)):
                break

            if not success:
                product = IslandProduct(self.device.image)
                if product.valid:
                    self.total = self.total.add_by_eq(SelectedGrids([product]))
                    self.device.click(ISLAND_CLICK_SAFE_AREA)
                    break
                else:
                    self.interval_clear(ROLE_SELECT_ENTER)

        return success

    def _project_character_select(self, click_button=None, check_button=None):
        """
        为岛屿项目选择指定角色。

        点击角色按钮后，若提供了角色校验按钮，则先确认选中头像正确，再点击确认。
        """
        click_timeout = Timer(1.5).start()
        confirm_clicked = False
        if click_button is not None:
            self.device.click(click_button)

        for _ in self.loop(skip_first=False, timeout=6):
            if self.appear(ISLAND_AMOUNT_MAX, offset=(20, 20)):
                return True
            # 游戏 bug：点击 ROLE_SELECT_CONFIRM 后页面可能返回到 ISLAND_MANAGEMENT_CHECK
            if self.island_in_management():
                return False

            confirm_visible = self.appear(ROLE_SELECT_CONFIRM, offset=(20, 20))
            if confirm_clicked and not confirm_visible:
                return True

            if confirm_visible:
                if check_button is not None and not self.appear(check_button, offset=(20, 20)):
                    if click_button is None:
                        return False
                    if click_timeout.reached():
                        logger.info('Character check mismatch, re-clicking character')
                        self.device.click(click_button)
                        confirm_clicked = False
                        click_timeout.reset()
                    continue
                if not confirm_clicked or click_timeout.reached():
                    if confirm_clicked:
                        logger.info('ROLE_SELECT_CONFIRM still appeared, re-clicking confirm')
                    self.device.click(ROLE_SELECT_CONFIRM)
                    confirm_clicked = True
                    click_timeout.reset()
                    self.interval_clear(ISLAND_MANAGEMENT_CHECK)
                continue

            if not confirm_clicked and click_timeout.reached():
                if click_button is None:
                    logger.warning('ROLE_SELECT_CONFIRM not appeared for selected character')
                    return False
                logger.info('ROLE_SELECT_CONFIRM not appeared, re-clicking character')
                self.device.click(click_button)
                click_timeout.reset()
                continue

        logger.warning('Island select role verification timeout')
        return False

    def _project_character_confirm_if_selected(self, character):
        check_button = self.get_character_check_button(character)
        if check_button is None:
            return False
        if not self.appear(ROLE_SELECT_CONFIRM, offset=(20, 20)):
            return False
        if not self.appear(check_button, offset=(20, 20)):
            return False

        logger.info(f'Character {self.readable_character_name(character)} already selected')
        return self._project_character_select(check_button=check_button)

    def project_character_select(self, character='manjuu'):
        """
        选择生产角色，支持按配置顺序尝试候选角色。

        Returns:
            str|None: 成功时返回选中的规范角色 key，失败时返回 None。
        """
        candidates = self.parse_character_candidates(character)
        if not candidates:
            candidates = ['manjuu']
        if 'manjuu' not in candidates:
            candidates.append('manjuu')

        logger.info(f'Island select role candidates: {candidates}')
        self.project_character_reset_position()

        unavailable = set()
        timeout = Timer(5, count=3).start()
        swipe_count = 0
        swipe_limit = 5
        det_ocr = AlOcr(name='zhcn' if server.server == 'cn' else 'en')
        for _ in self.loop(skip_first=False):
            if timeout.reached():
                break

            image = self.image_crop((0, 0, 910, 720), copy=False)
            det_results = det_ocr.det(image)
            if det_results:
                # 将识别结果分组为角色卡片以识别“工作中”和体力状态。
                cards = self._group_character_cards(det_results)
                grid_checked = False
                grid_cards = []

                if self.DEBUG_ISLAND_PROJECT:
                    self._save_island_debug(image, cards)

                for candidate in candidates:
                    if candidate in unavailable:
                        continue
                    if self._project_character_confirm_if_selected(candidate):
                        return candidate
                    logger.debug(f'Checking character candidate: {self.readable_character_name(candidate)}')
                    result = self._project_character_select_from_cards(
                        candidate, image, cards, grid_checked=grid_checked
                    )
                    if result in ['needs_grid', 'not_found'] and not grid_checked:
                        cards, grid_cards = self._append_character_grid_cards(
                            image, cards, det_results, det_ocr, candidates, unavailable
                        )
                        grid_checked = True
                        result = self._project_character_select_from_cards(
                            candidate, image, cards, grid_checked=True
                        )
                    if result == 'not_found' and grid_checked:
                        result = self._project_character_probe_grid_cards(candidate, grid_cards, det_ocr)
                    if result == 'not_found':
                        logger.debug(f'Character {self.readable_character_name(candidate)} not found on current page')
                    if result == 'selected':
                        return candidate
                    if result == 'unavailable':
                        unavailable.add(candidate)
                        logger.info(f'Character {self.readable_character_name(candidate)} unavailable')

            remain = [candidate for candidate in candidates if candidate not in unavailable]
            if not remain:
                break

            names = ', '.join(self.readable_character_name(candidate) for candidate in remain)
            if swipe_count < swipe_limit:
                logger.info(f'No available character {names} found, swiping down ({swipe_count + 1}/{swipe_limit})')
                self.drag_page((0, -250), (200, 300, 700, 550), 0.6)
                swipe_count += 1
            else:
                logger.info(f'No available character {names} was found')
                break
        return None

    def project_character_reset_position(self):
        for _ in range(5):
            self.drag_page((0, 300), (200, 300, 700, 550), 0.2)
        self.device.click_record_remove('DRAG')

    def _project_character_select_from_cards(self, character, image, cards, grid_checked=False):
        """
        从当前页面的角色卡片中按候选选择角色。

        普通角色在列表中唯一；一旦检测到工作中或体力不足，直接判定该候选不可用。
        工作啾可能有多个，因此只跳过当前不可用卡片并继续寻找其他工作啾。
        """
        matched = False
        found_unavailable = False
        for card in cards:
            if not self.character_name_match(card['name'], character):
                continue
            matched = True
            if card['working']:
                logger.info(f'Character {card["name"]} is working')
                found_unavailable = True
                if character != 'manjuu':
                    return 'unavailable'
                continue
            stamina = card.get('stamina')
            if stamina is not None and stamina < 40:
                logger.info(f'Character {card["name"]} stamina {stamina} < 40')
                found_unavailable = True
                if character != 'manjuu':
                    return 'unavailable'
                continue
            if stamina is None and character != 'manjuu' and not grid_checked:
                return 'needs_grid'

            click_button = self._project_character_click_button(character, image, card)
            check_button = self.get_character_check_button(character)
            return 'selected' if self._project_character_select(click_button, check_button=check_button) else 'unavailable'

        if matched and found_unavailable:
            return 'unavailable'
        return 'not_found'

    @classmethod
    def _character_grid_area(cls, column, row, offset):
        ox, oy = cls.ROLE_CARD_ORIGIN
        dx, dy = cls.ROLE_CARD_DELTA
        x1 = ox + dx * column + offset[0]
        y1 = oy + dy * row + offset[1]
        x2 = ox + dx * column + offset[2]
        y2 = oy + dy * row + offset[3]
        return x1, y1, x2, y2

    @staticmethod
    def _box_from_area(area):
        x1, y1, x2, y2 = area
        return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]

    @staticmethod
    def _crop_area(image, area):
        height, width = image.shape[:2]
        x1, y1, x2, y2 = area
        x1 = max(0, min(width, int(x1)))
        x2 = max(0, min(width, int(x2)))
        y1 = max(0, min(height, int(y1)))
        y2 = max(0, min(height, int(y2)))
        return image[y1:y2, x1:x2]

    @staticmethod
    def _parse_character_stamina(text):
        m = re.search(r'(\d+)\s*/\s*\d+', str(text or ''))
        if not m:
            return None
        return int(m.group(1))

    @staticmethod
    def _box_center(box):
        center = np.mean(box, axis=0)
        return float(center[0]), float(center[1])

    @classmethod
    def _known_character_card(cls, card):
        return any(cls.character_name_match(card['name'], character) for character in CHARACTER_NAME_MAP)

    @classmethod
    def _area_contains_box_center(cls, area, box, margin=10):
        x1, y1, x2, y2 = area
        cx, cy = cls._box_center(box)
        return x1 - margin <= cx <= x2 + margin and y1 - margin <= cy <= y2 + margin

    def _slot_has_detected_known_character(self, cards, card_area):
        return any(
            self._known_character_card(card)
            and self._area_contains_box_center(card_area, card['name_box'])
            for card in cards
        )

    def _character_grid_slots(self, cards):
        known = [card for card in cards if self._known_character_card(card)]
        slots = []
        seen = set()

        rows = []
        for card in sorted(known, key=lambda c: self._box_center(c['name_box'])[1]):
            _, y = self._box_center(card['name_box'])
            for row in rows:
                if abs(row['y'] - y) < 45:
                    row['cards'].append(card)
                    row['y'] = float(np.mean([self._box_center(item['name_box'])[1] for item in row['cards']]))
                    break
            else:
                rows.append({'y': y, 'cards': [card]})

        for row in rows:
            if len(row['cards']) < 2:
                continue
            centers = sorted(self._box_center(card['name_box']) for card in row['cards'])
            xs = [center[0] for center in centers]
            deltas = [
                b - a for a, b in zip(xs, xs[1:])
                if 80 <= b - a <= 180
            ]
            if deltas:
                delta = float(np.median(deltas))
            else:
                delta = float(self.ROLE_CARD_DELTA[0])

            x = min(xs)
            while x - delta > 40:
                x -= delta
            while x < 900:
                key = (round(x / 8), round(row['y'] / 8))
                if key not in seen:
                    seen.add(key)
                    slots.append(self._character_slot_area_from_name_center(x, row['y']))
                x += delta

        if slots:
            return slots

        columns, rows = self.ROLE_CARD_GRID
        for row in range(rows):
            for column in range(columns):
                name_area = self._character_grid_area(column, row, self.ROLE_CARD_NAME_OFFSET)
                stamina_area = self._character_grid_area(column, row, self.ROLE_CARD_STAMINA_OFFSET)
                card_area = self._character_grid_area(column, row, (0, 0, *self.ROLE_CARD_SIZE))
                slots.append((name_area, stamina_area, card_area))
        return slots

    @classmethod
    def _character_slot_area_from_name_center(cls, x, y):
        name_area = (x - 64, y - 18, x + 64, y + 18)
        stamina_area = (x - 42, y + 10, x + 98, y + 38)
        card_area = (x - 64, y - 112, x + 64, y + 52)
        return name_area, stamina_area, card_area

    def _read_character_grid_cards(self, image, cards, det_results, det_ocr):
        slots = self._character_grid_slots(cards)
        name_images = [self._crop_area(image, name_area) for name_area, _, _ in slots]
        stamina_images = [self._crop_area(image, stamina_area) for _, stamina_area, _ in slots]

        names = det_ocr.ocr_for_single_lines(name_images)
        stamina_texts = det_ocr.ocr_for_single_lines(stamina_images)
        logger.debug(f'Character grid OCR: {[name for name in names if name]}')
        grid_cards = []
        for (name_area, stamina_area, card_area), name, stamina_text in zip(slots, names, stamina_texts):
            working, stamina = self._character_grid_status(det_results, card_area)
            stamina = stamina if stamina is not None else self._parse_character_stamina(stamina_text)
            grid_cards.append({
                'name': name,
                'name_box': self._box_from_area(name_area),
                'card_box': self._box_from_area(card_area),
                'working': working,
                'stamina': stamina,
                'detected_known': self._slot_has_detected_known_character(cards, card_area),
            })
        return grid_cards

    def _append_character_grid_cards(self, image, cards, det_results, det_ocr, candidates, unavailable):
        """
        补充卡片网格区域的单行 OCR 结果。

        通用 OCR 有时会漏掉短名称或把个别字识别错。这里按当前页面已知卡片推断网格，
        再补读每个槽位的名称和体力，供候选匹配和后续详情页校验使用。
        """
        active_candidates = [candidate for candidate in candidates if candidate not in unavailable]
        if not active_candidates:
            return cards, []

        grid_cards = self._read_character_grid_cards(image, cards, det_results, det_ocr)
        for grid_card in grid_cards:
            name = grid_card['name']
            candidate = next((
                candidate for candidate in active_candidates
                if self.character_name_match(name, candidate)
            ), None)
            if candidate is None:
                continue

            existing = next((
                card for card in cards
                if self.character_name_match(card['name'], candidate)
            ), None)
            if existing is not None:
                if grid_card['working']:
                    existing['working'] = True
                if existing.get('stamina') is None and grid_card['stamina'] is not None:
                    existing['stamina'] = grid_card['stamina']
                    logger.info(f'Character grid OCR stamina: {name}, stamina={grid_card["stamina"]}')
                continue

            logger.info(f'Character grid OCR fallback: {name}, stamina={grid_card["stamina"]}')
            cards.append(grid_card)
        return cards, grid_cards

    def _selected_character_detail_name(self, det_ocr):
        image = self.device.image
        if image is None:
            return ''
        area = self.ROLE_DETAIL_NAME_AREA
        text = det_ocr.ocr_for_single_lines([self._crop_area(image, area)])[0]
        logger.debug(f'Character detail OCR: {text}')
        return text

    def _project_character_probe_select(self, character, click_button, det_ocr):
        click_timeout = Timer(1.5).start()
        mismatch_timeout = Timer(0.5, count=1).start()
        confirm_clicked = False
        self.device.click(click_button)

        for _ in self.loop(skip_first=False, timeout=6):
            if self.appear(ISLAND_AMOUNT_MAX, offset=(20, 20)):
                return 'selected'
            if self.island_in_management():
                return 'mismatch'

            confirm_visible = self.appear(ROLE_SELECT_CONFIRM, offset=(20, 20))
            if confirm_clicked and not confirm_visible:
                return 'selected'

            if confirm_visible:
                detail_name = self._selected_character_detail_name(det_ocr)
                if not detail_name:
                    continue
                if not self.character_detail_name_match(detail_name, character):
                    if not mismatch_timeout.reached():
                        continue
                    logger.debug(
                        f'Character detail mismatch: {detail_name} != '
                        f'{self.readable_character_name(character)}'
                    )
                    return 'mismatch'
                if not confirm_clicked:
                    logger.info(f'Character detail matched: {detail_name}')
                if not confirm_clicked or click_timeout.reached():
                    if confirm_clicked:
                        logger.info('ROLE_SELECT_CONFIRM still appeared, re-clicking confirm')
                    self.device.click(ROLE_SELECT_CONFIRM)
                    confirm_clicked = True
                    click_timeout.reset()
                    self.interval_clear(ISLAND_MANAGEMENT_CHECK)
                continue

            if not confirm_clicked and click_timeout.reached():
                self.device.click(click_button)
                click_timeout.reset()
                mismatch_timeout.reset()
                continue

        logger.warning('Island select role detail verification timeout')
        return 'timeout'

    def _project_character_probe_grid_cards(self, character, grid_cards, det_ocr):
        if not grid_cards:
            return 'not_found'

        logger.info(f'Verify ambiguous cards for {self.readable_character_name(character)}')
        for card in grid_cards:
            if self.character_name_match(card['name'], character):
                continue
            if card.get('detected_known'):
                continue
            if self._known_character_card(card):
                continue
            if card['working']:
                continue
            stamina = card.get('stamina')
            if stamina is None or stamina < 40:
                continue

            click_button = self._project_character_click_button(character, self.device.image, card)
            result = self._project_character_probe_select(character, click_button, det_ocr)
            if result == 'selected':
                return 'selected'
            if result == 'timeout':
                return 'unavailable'
        return 'not_found'

    @classmethod
    def _character_grid_status(cls, det_results, card_area):
        x1, y1, x2, y2 = card_area
        working = False
        stamina = None
        for txt, box, _ in det_results:
            cx, cy = np.mean(box, axis=0)
            if not (x1 - 10 <= cx <= x2 + 10 and y1 - 10 <= cy <= y2 + 10):
                continue
            if '工作中' in txt:
                working = True
            if stamina is None:
                stamina = cls._parse_character_stamina(txt)
        return working, stamina

    def project_character_select_one(self, character):
        """
        选择单个角色候选。
        """
        timeout = Timer(5, count=3).start()
        swipe_count = 0
        det_ocr = AlOcr(name='zhcn' if server.server == 'cn' else 'en')
        for _ in self.loop(skip_first=False):
            if timeout.reached():
                return False

            image = self.image_crop((0, 0, 910, 1280), copy=False)
            det_results = det_ocr.det(image)
            if det_results:
                # 将识别结果分组为角色卡片以识别“工作中”和体力状态。
                cards = self._group_character_cards(det_results)

                if self.DEBUG_ISLAND_PROJECT:
                    self._save_island_debug(image, cards)

                for card in cards:
                    if not self.character_name_match(card['name'], character):
                        continue
                    if card['working']:
                        logger.info(f'Character {card["name"]} is working')
                        continue
                    stamina = card.get('stamina')
                    if stamina is not None and stamina < 40:
                        logger.info(f'Character {card["name"]} stamina {stamina} < 40')
                        if character != 'manjuu':
                            return False
                        continue

                    click_button = self._project_character_click_button(character, image, card)
                    check_button = self.get_character_check_button(character)
                    return self._project_character_select(click_button, check_button=check_button)

            name = self.readable_character_name(character)
            if swipe_count < 5:
                logger.info(f'No character {name} found, swiping down ({swipe_count + 1}/5)')
                self.drag_page((0, -250), (200, 300, 700, 550), 0.6)
                swipe_count += 1
            else:
                logger.info(f'No character {name} was found')
                return False

    @staticmethod
    def get_character_template(character):
        return globals().get(f'TEMPLATE_{character.upper()}')

    @staticmethod
    def get_character_check_button(character):
        return globals().get(f'PROJECT_{character.upper()}_CHECK')

    def _project_character_click_button(self, character, image, card):
        # OCR 已经确认了目标卡片，点击角色名区域比头像模板更不容易误中相似立绘。
        box = card['name_box']
        cx = int(sum(p[0] for p in box) / len(box))
        cy = int(sum(p[1] for p in box) / len(box))
        return Button(area=(cx, cy, cx, cy), color=(), button=(cx, cy, cx, cy), name=f'CHAR_{character}')

    def _group_character_cards(self, det_results):
        working_label = '工作中'
        working_boxes = []
        stamina_boxes = []
        others = []
        for txt, box, score in det_results:
            if working_label in txt:
                working_boxes.append(box)
            elif re.search(r'\d+/\d+', txt):
                stamina_boxes.append((txt, box))
            else:
                others.append({'txt': txt, 'box': box, 'score': score})

        cards = []
        used_working = set()
        used_stamina = set()
        others.sort(key=lambda x: (np.mean(x['box'], axis=0)[1], np.mean(x['box'], axis=0)[0]))

        for item in others:
            txt, box = item['txt'], item['box']
            bc = np.mean(box, axis=0)

            associated_working = None
            for i, w_box in enumerate(working_boxes):
                if i in used_working: continue
                wc = np.mean(w_box, axis=0)
                if abs(wc[0] - bc[0]) < 60 and 30 < bc[1] - wc[1] < 150:
                    associated_working = w_box
                    used_working.add(i)
                    break

            stamina = None
            for i, (stxt, sbox) in enumerate(stamina_boxes):
                if i in used_stamina: continue
                sc = np.mean(sbox, axis=0)
                if abs(sc[0] - bc[0]) < 100 and abs(sc[1] - bc[1]) < 80:
                    value = self._parse_character_stamina(stxt)
                    if value is not None:
                        stamina = value
                        used_stamina.add(i)
                        break

            if associated_working:
                all_pts = np.array(box + associated_working)
                x_min, y_min = np.min(all_pts, axis=0)
                x_max, y_max = np.max(all_pts, axis=0)
                card_box = [[x_min - 10, y_min - 20], [x_max + 10, y_min - 20], [x_max + 10, y_max + 10], [x_min - 10, y_max + 10]]
                working = True
            else:
                x_min, y_min = np.min(box, axis=0)
                x_max, y_max = np.max(box, axis=0)
                card_box = [[x_min - 10, y_min - 100], [x_max + 10, y_min - 100], [x_max + 10, y_max + 10], [x_min - 10, y_max + 10]]
                working = False

            cards.append({
                'name': txt,
                'name_box': box,
                'card_box': card_box,
                'working': working,
                'stamina': stamina,
            })
        return cards

    def _save_island_debug(self, image, cards):
        """
        保存带有角色卡片框的调试图像。
        """
        folder = 'debug_img'
        if not os.path.exists(folder):
            os.makedirs(folder)

        draw = image.copy()
        if len(draw.shape) == 2:
            draw = cv2.cvtColor(draw, cv2.COLOR_GRAY2BGR)
        elif draw.shape[2] == 3:
            # AzurPilot 内部使用 RGB，cv2 保存需要 BGR
            draw = cv2.cvtColor(draw, cv2.COLOR_RGB2BGR)

        for card in cards:
            pts = np.array(card['card_box'], dtype=np.int32).reshape((-1, 1, 2))
            # BGR: 红色表示工作中，绿色表示空闲
            color = (0, 0, 255) if card['working'] else (0, 255, 0)
            cv2.polylines(draw, [pts], True, color, 2)

            name = card['name']
            label = f"{name}{'(BUSY)' if card['working'] else ''}"
            # 绘制文字标签
            x, y = int(pts[0][0][0]), int(pts[0][0][1])
            cv2.putText(draw, label, (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        now = int(time.time() * 1000)
        save_path = os.path.join(folder, f'island_card_{now}.png')
        cv2.imwrite(save_path, draw)
        logger.info(f'Island debug image saved: {save_path}')

    def get_current_product(self, project_id):
        """
        获取当前截图中选中的产品。

        Returns:
            ProductItem: 当前选中的物品
        """
        image = self.image_crop(ISLAND_PRODUCT_ITEMS, copy=False)
        y_top = ISLAND_PRODUCT_ITEMS.area[1]
        line = cv2.reduce(image, 1, cv2.REDUCE_AVG)
        # 检测蓝色分隔线
        line = color_similarity_2d(line, color=(57, 189, 255))[:, 0]
        parameters = {
            'height': 200,
            'distance': 50,
        }
        peaks, _ = signal.find_peaks(line, **parameters)
        peaks = np.array(peaks) + y_top
        product_order = list(items_data.get(project_id, {}).values())
        if len(peaks) < 2:
            return ProductItem.from_ocr_results(self.device.image, project_id, product_order)
        current = ProductItem(self.device.image, peaks, project_id)
        if not any(item.valid and item.name for item in current.items):
            return ProductItem.from_ocr_results(self.device.image, project_id, product_order)
        return current

    def product_select(self, option, project_id, trial=2):
        """
        在物品列表中选择指定产品。

        Args:
            option (str): 要选择的产品名称
            trial (int): 重试次数

        Returns:
            bool: 是否成功选择
        """
        logger.hr('Island Select Product')
        last_item = None
        bottom_item = None
        retry = trial
        click_interval = Timer(1)
        select_timeout = Timer(2, count=3)
        pending_option = None
        for _ in self.loop():
            current = self.get_current_product(project_id)
            if trial > 0 and not len(current.items):
                trial -= 1
                continue
            if trial <= 0:
                self.ui_ensure_management_page()
                return False

            if option == current.name:
                if getattr(current, 'is_fallback', False) and pending_option != option:
                    target = next((item for item in current.items if item.name == option), None)
                    if target is not None and click_interval.reached():
                        logger.info(f'Fallback selected item {option}, click to verify')
                        self.device.click(target.button)
                        self.device.sleep(0.2)
                        click_interval.reset()
                        select_timeout.reset()
                        pending_option = option
                        continue
                logger.info(f'Selected item {option}')
                return True

            if pending_option == option and select_timeout.reached():
                logger.warning(f'Product {option} click did not become selected')
                self.ui_ensure_management_page()
                return False

            drag = True
            for item in current.items:
                if option == item.name:
                    if click_interval.reached():
                        self.device.click(item.button)
                        self.device.sleep(0.2)
                        click_interval.reset()
                        if pending_option != option:
                            select_timeout.reset()
                        pending_option = option
                    drag = False
            
            if bottom_item == current.items[-1]:
                if retry > 0:
                    retry -= 1
                    continue
                logger.info(f'Reach the bottom of items, did not match item {option}')
                self.ui_ensure_management_page()
                return False

            # 连续两次拖拽中如果产品不同则清除记录
            if last_item is not None and last_item != current:
                self.device.click_record.pop()
                self.device.click_record.pop()

            if drag:
                last_item = current
                bottom_item = current.items[-1]
                self.device.click(bottom_item.button)
                self.drag_page((0, -300), ISLAND_PRODUCT_ITEMS.area, 0.5)

    def product_select_confirm(self):
        """
        产品选择确认后启动生产。

        Returns:
            str: 启动状态
        """
        logger.info('Island product confirm')
        last = None
        success = False
        timeout = Timer(1.5, count=3).start()
        for _ in self.loop():
            if timeout.reached():
                break

            if not success:
                if self.image_color_count(PROJECT_START, color=(151, 155, 155), threshold=221, count=200):
                    logger.warning('Product requirement is not satisfied, quitting and retrying')
                    self.ui_ensure_management_page()
                    return 'requirement_unsatisfied'

                if self.appear_then_click(ISLAND_AMOUNT_MAX, offset=(5, 5), interval=2):
                    timeout.reset()
                    continue

                button = PROJECT_START
                # OCR_PRODUCTION_TIME 的偏移量由 PROJECT_START 决定
                self.appear(button, offset=(100, 0))
                offset = tuple(np.subtract(button.button, button._button)[:2])
                product = IslandProduct(self.device.image, new=True, offset=offset)
                if product == last:
                    success = True
                    self.total = self.total.add_by_eq(SelectedGrids([product]))
                    timeout.reset()
                    continue
                last = product
            else:
                if self.appear_then_click(PROJECT_START, offset=(100, 0), interval=2):
                    timeout.reset()
                    self.interval_clear(ISLAND_MANAGEMENT_CHECK)
                    continue

                if self.info_bar_count():
                    self.ui_ensure_management_page()
                    return 'started'
                if self.island_in_management():
                    return 'started'

        logger.warning('Island product confirm timeout')
        self.ui_ensure_management_page()
        return 'confirm_timeout'

    def project_receive_and_start(self, proj, button, character_info, option_info, ensure=True):
        """
        领取并启动当前页面上的项目。

        Args:
            proj (IslandProject): 项目对象
            button (Button): 项目按钮
            character_info (dict): 当前槽位的角色候选信息
            option_info (dict): 当前槽位的产品候选信息
            ensure (bool): 启动后是否调用 ensure_project()
        """
        if not self.project_receive(button):
            return 'slot_skipped'
        selected = self.project_character_select(character_info['candidates'])
        if selected is None:
            logger.warning('Island select role failed, skip this slot')
            self.ui_ensure_management_page()
            return 'character_unavailable'
        if not self.product_select(option_info['option'], proj.id):
            return 'product_select_failed'

        status = self.product_select_confirm()
        if status != 'started':
            self.ensure_project(proj)
            return status
        self.ui_ensure_management_page()
        if ensure:
            self.ensure_project(proj)
        logger.info(f'Island project started with {selected}: {option_info["option"]}')
        return 'started'

    def island_project_character(self, project: IslandProject):
        """
        获取项目的角色配置列表。

        Args:
            project (IslandProject): 项目对象

        Returns:
            list[dict]: 各槽位的角色候选信息
        """
        proj_id = project.id
        out = []
        for proj_slot in range(1, project.slot + 1):
            raw = self.config.__getattribute__(f'Island{proj_id}_Character{proj_slot}')
            out.append({
                'slot': proj_slot,
                'raw': raw,
                'candidates': self.parse_character_candidates(raw),
            })
        return out

    def island_project_option(self, project: IslandProject):
        """
        获取项目的产品配置列表。

        Args:
            project (IslandProject): 项目对象

        Returns:
            list[dict|None]: 各槽位的产品候选信息
        """
        slot_option = []
        proj_id = project.id
        for proj_slot in range(1, project.slot + 1):
            raw = self.config.__getattribute__(f'Island{proj_id}_Option{proj_slot}')
            if self.option_is_empty(raw):
                slot_option.append(None)
                continue

            if proj_id == self.RANCH_PROJECT_ID:
                raw_candidates = self.parse_config_list(raw)
                fixed_raw = raw_candidates[0] if raw_candidates else raw
                resolved = self.resolve_product_option(proj_id, fixed_raw)
                candidates = [resolved] if resolved else []
                cursor_key = None
                cursor_before = 0
                cursor_after = 0
                rotates = False
            else:
                candidates = [
                    self.resolve_product_option(proj_id, option)
                    for option in self.parse_config_list(raw)
                    if not self.option_is_empty(option)
                ]
                candidates = [option for option in candidates if option]
                cursor_key = self.product_cursor_key(proj_id, proj_slot)
                signature = self.product_option_signature(candidates)
                cursor_before = self.get_product_cursor(proj_id, proj_slot, signature=signature)
                cursor_after = cursor_before + 1
                rotates = len(candidates) > 1

            if not candidates:
                slot_option.append(None)
                continue
            option = candidates[cursor_before % len(candidates)]
            slot_option.append({
                'slot': proj_slot,
                'raw': raw,
                'candidates': candidates,
                'option': option,
                'cursor_key': cursor_key,
                'cursor_before': cursor_before,
                'cursor_after': cursor_after,
                'rotates': rotates,
                'signature': self.product_option_signature(candidates),
            })
        return slot_option

    def island_project_run(self, names, trial=2):
        """
        执行岛屿项目流程：领取和启动项目。

        Args:
            names (list[str]): 需要收取的岛屿名称列表
            trial (int): 检测失败重试次数

        Returns:
            list[timedelta]: 未来完成时间列表
        """
        logger.hr('Island Project Run', level=1)
        self.project = SelectedGrids([])
        self.total = SelectedGrids([])
        self.reset_island_storage_cache()
        self.ensure_project(names[0])
        end = False
        timeout = Timer(3, count=3).start()
        for _ in self.loop():
            if timeout.reached():
                break

            projects = self.project_detect(self.device.image)
            if trial > 0 and not projects:
                trial -= 1
                continue
            projects: SelectedGrids = projects.filter(
                lambda proj: proj.name in names and proj.name not in self.project.get('name'))
            self.project = self.project.add_by_eq(projects)
            self.projects_dirty = False

            for proj in projects:
                logger.hr('Island Project')
                logger.attr('Project_name', proj)
                if proj.name == names[-1]:
                    end = True
                
                character_config = self.island_project_character(proj)
                option_config = self.island_project_option(proj)
                option_num = len(option_config)
                for button, character_info, option_info, index in zip(
                        proj.slot_buttons.buttons, character_config, option_config, range(option_num)):
                    if option_info is None:
                        continue
                    self.character = ', '.join(character_info['candidates']) or str(character_info['raw'])
                    logger.attr('Character', self.character)
                    slot_started = False
                    skipped_options = set()
                    for current_option in self.product_candidate_sequence(option_info):
                        option_key = str(current_option['option'])
                        if option_key in skipped_options:
                            logger.info(
                                f'Product {current_option["option"]} already failed in this slot, '
                                'skip duplicate candidate'
                            )
                            continue
                        logger.attr('Product', current_option['option'])
                        last_status = None
                        attempt_count = 0
                        # retry 3 times because of a game bug or temporary OCR/confirm failure
                        for _ in range(3):
                            attempt_count += 1
                            ensure = not end or index != option_num - 1
                            status = self.project_receive_and_start(
                                proj, button, character_info, current_option, ensure
                            )
                            last_status = status
                            if self.projects_dirty:
                                break
                            if status == 'started':
                                self.advance_product_cursor(current_option)
                                self.save_island_storage()
                                slot_started = True
                                break
                            if status in ['slot_skipped', 'character_unavailable', 'requirement_unsatisfied']:
                                break
                        if self.projects_dirty:
                            break
                        if slot_started or last_status in ['slot_skipped', 'character_unavailable']:
                            break
                        if last_status == 'requirement_unsatisfied':
                            logger.warning(
                                f'Product {current_option["option"]} requirement is not satisfied, '
                                'try next candidate'
                            )
                        else:
                            logger.warning(
                                f'Product {current_option["option"]} failed after {attempt_count} attempts: '
                                f'{last_status}, try next candidate'
                            )
                        skipped_options.add(option_key)
                    if self.projects_dirty:
                        break
                timeout.reset()
                if self.projects_dirty:
                    break

            if self.projects_dirty:
                continue
            if end:
                break
            self.drag_page((0, -500), ISLAND_PROJECT_SWIPE.area, 0.6)

        self.save_island_storage()

        # task delay
        future_finish = sorted([f for f in self.total.get('finish_time') if f is not None])
        logger.info(f'Project finish: {[str(f) for f in future_finish]}')
        if not len(future_finish):
            logger.info('No island project running')
        return future_finish
