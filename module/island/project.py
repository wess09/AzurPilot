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
            result = result.replace('蛮', '蜜').replace('汗', '汁').replace('纠', '组').replace('离', '禽').replace('莱', '菜').replace('内', '肉').replace('克', '苋')
            result = re.sub(r'[^\u4e00-\u9fff]', '', result)
            if '冰咖' in result:
                result = '冰咖啡'
            if '莓果香橙' in result:
                result = '莓果香橙甜点组'
            if '莉精油' in result:
                result = '茉莉精油'
        elif server.server == 'en':
            result = re.sub(r"[\s'-]+", "", result)
            result = result.lower()
        return result


class ProductItem:
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
        return item

    @classmethod
    def from_ocr_results(cls, image, parent_project_id, product_order):
        item = cls.empty(image, parent_project_id)
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
            y1 = int(max(top, cy - 65))
            y2 = int(min(bottom, cy + 65))
            area = (left + 20, y1, right - 20, y2)
            row = cls.empty(image, parent_project_id)
            row.y = (y1, y2)
            row.name = resolved
            row.button = Button(area=area, color=(), button=area, name=f'ISLAND_ITEM_{resolved}')
            item.items.append(row)

        if item.items:
            logger.info(f'Product OCR fallback rows: {[row.name for row in item.items]}')
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
    project = SelectedGrids([])
    total = SelectedGrids([])
    character: str

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

    def _project_character_select(self, click_button, check_button=None):
        """
        为岛屿项目选择指定角色。

        点击角色按钮，等待确认，如果确认按钮未出现则重新点击。

        Args:
            click_button (Button): 角色按钮
            check_button: 未使用，保留兼容性
        """
        click_timeout = Timer(1.5).start()
        confirm_clicked = False
        self.device.click(click_button)
        self.device.sleep(0.5)  # 等待 UI 稳定

        for _ in self.loop():
            self.device.screenshot()  # 强制获取新截图
            # 结束条件
            if self.appear(ISLAND_AMOUNT_MAX, offset=(20, 20)):
                return True
            # 游戏 bug：点击 ROLE_SELECT_CONFIRM 后页面可能返回到 ISLAND_MANAGEMENT_CHECK
            if self.island_in_management():
                return False

            if self.appear(ROLE_SELECT_CONFIRM, offset=(20, 20)):
                if not confirm_clicked:
                    self.device.sleep(0.3)
                    self.device.click(ROLE_SELECT_CONFIRM)
                    confirm_clicked = True
                    self.interval_clear(ISLAND_MANAGEMENT_CHECK)
                continue

            if not confirm_clicked and click_timeout.reached():
                logger.info('ROLE_SELECT_CONFIRM not appeared, re-clicking character')
                self.device.click(click_button)
                self.device.sleep(0.5)
                click_timeout.reset()
                continue

    def project_character_select(self, character='manjuu'):
        """
        选择生产角色。

        Args:
            character (str): 角色名称

        Returns:
            bool: 是否成功选择
        """
        logger.info('Island select role')
        timeout = Timer(5, count=3).start()
        swipe_count = 0
        target_name = CHARACTER_NAME_MAP.get(character, {}).get(server.server,
                       CHARACTER_NAME_MAP.get(character, {}).get('cn', character))
        det_ocr = AlOcr(name='zhcn' if server.server == 'cn' else 'en')
        for _ in self.loop():
            if timeout.reached():
                self.ui_ensure_management_page()
                return False

            image = self.image_crop((0, 0, 910, 1280), copy=False)
            det_results = det_ocr.det(image)
            if det_results:
                # 将识别结果分组为角色卡片以识别"工作中"状态
                cards = self._group_character_cards(det_results)

                # 检查调试开关
                if self.DEBUG_ISLAND_PROJECT:
                    self._save_island_debug(image, cards)

                found_busy = False
                for card in cards:
                    if target_name in card['name'] or card['name'] in target_name:
                        if card['working']:
                            logger.info(f'Character {card["name"]} is working')
                            found_busy = True
                            continue
                        stamina = card.get('stamina')
                        if stamina is not None and stamina < 40:
                            logger.info(f'Character {card["name"]} stamina {stamina} < 40')
                            found_busy = True
                            continue

                        box = card['name_box']
                        cx = int(sum(p[0] for p in box) / len(box))
                        cy = int(sum(p[1] for p in box) / len(box))
                        click_button = Button(area=(cx, cy, cx, cy), color=(), button=(cx, cy, cx, cy), name=f'CHAR_{character}')
                        return self._project_character_select(click_button)

                if found_busy:
                    logger.info(f'{target_name} unavailable, use manjuu')
                    character = 'manjuu'
                    target_name = CHARACTER_NAME_MAP.get(character, {}).get(server.server,
                                   CHARACTER_NAME_MAP.get(character, {}).get('cn', character))
                    self.drag_page((0, -300), (200, 300, 700, 550), 0.3)
                    self.device.sleep(0.5)
                    continue

            name = ' '.join(map(lambda x: x.capitalize(), character.split('_')))
            if swipe_count < 5:
                logger.info(f'No character {name} found, swiping down ({swipe_count + 1}/5)')
                self.drag_page((0, -250), (200, 300, 700, 550), 0.6)
                self.device.sleep(0.5)
                swipe_count += 1
            else:
                logger.info(f'No character {name} was found, use manjuu')
                character = 'manjuu'
                target_name = CHARACTER_NAME_MAP.get(character, {}).get(server.server,
                               CHARACTER_NAME_MAP.get(character, {}).get('cn', character))
                self.drag_page((0, -300), (200, 300, 700, 550), 0.3)
                self.device.sleep(0.5)
            continue

    @staticmethod
    def get_character_template(character):
        return globals().get(f'TEMPLATE_{character.upper()}', TEMPLATE_MANJUU)

    @staticmethod
    def get_character_check_button(character):
        return globals().get(f'PROJECT_{character.upper()}_CHECK', PRODUCT_MANJUU_CHECK)

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
                    m = re.search(r'(\d+)/(\d+)', stxt)
                    if m:
                        stamina = int(m.group(1))
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
        for _ in self.loop():
            current = self.get_current_product(project_id)
            if trial > 0 and not len(current.items):
                trial -= 1
                continue
            if trial <= 0:
                self.ui_ensure_management_page()
                return False

            if option == current.name:
                logger.info(f'Selected item {option}')
                return True

            drag = True
            for item in current.items:
                if option == item.name:
                    if click_interval.reached():
                        self.device.click(item.button)
                        self.device.sleep(0.2)
                        click_interval.reset()
                        # OCR fallback rows cannot report the selected item; the confirm step validates the click.
                        if not current.name:
                            return True
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
            bool: 是否成功启动
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
                    if self.appear(PRODUCT_MANJUU_CHECK, offset=(20, 20)):
                        self.ui_ensure_management_page()
                        return True
                    else:
                        logger.warning('Product requirement is not satisfied, quitting and retrying')
                        self.ui_ensure_management_page()
                        return False

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
                    return True
                if self.island_in_management():
                    return True

    def project_receive_and_start(self, proj, button, character, option, project_id, ensure=True):
        """
        领取并启动当前页面上的项目。

        Args:
            proj (IslandProject): 项目对象
            button (Button): 项目按钮
            character (str): 角色名称
            option (str): 产品选项
            ensure (bool): 启动后是否调用 ensure_project()
        """
        if not self.project_receive(button):
            return True
        if not self.project_character_select(character):
            logger.warning('Island select role failed due to game bug, retrying')
            return False
        if not self.product_select(option, project_id):
            return True
        if not self.product_select_confirm():
            self.character = 'manjuu'
            self.ensure_project(proj)
            return False
        self.ui_ensure_management_page()
        if ensure:
            self.ensure_project(proj)
        return True

    def island_project_character(self, project: IslandProject):
        """
        获取项目的角色配置列表。

        Args:
            project (IslandProject): 项目对象

        Returns:
            list[str]: 各槽位的角色名称列表
        """
        proj_id = project.id
        return [self.config.__getattribute__(f'Island{proj_id}_Character{proj_slot}')
                for proj_slot in range(1, project.slot + 1)]

    def island_project_option(self, project: IslandProject):
        """
        获取项目的产品配置列表。

        Args:
            project (IslandProject): 项目对象

        Returns:
            list[str]: 各槽位的产品名称列表
        """
        slot_option = []
        proj_id = project.id
        for proj_slot in range(1, project.slot + 1):
            option = self.config.__getattribute__(f'Island{proj_id}_Option{proj_slot}')
            if not option or option == 0 or option == '不生产':
                slot_option.append(None)
                continue
            if isinstance(option, int):
                slot_option.append(deep_get(items_data, [proj_id, option]))
            else:
                slot_option.append(option)
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

            for proj in projects:
                logger.hr('Island Project')
                logger.attr('Project_name', proj)
                if proj.name == names[-1]:
                    end = True
                
                character_config = self.island_project_character(proj)
                option_config = self.island_project_option(proj)
                option_num = len(option_config)
                for button, character, option, index in zip(
                        proj.slot_buttons.buttons, character_config, option_config, range(option_num)):
                    if option is None:
                        continue
                    self.character = character
                    # retry 3 times because of a game bug
                    for _ in range(3):
                        ensure = not end or index != option_num - 1
                        if self.project_receive_and_start(proj, button, self.character, option, proj.id, ensure):
                            break
                timeout.reset()

            if end:
                break
            self.drag_page((0, -500), ISLAND_PROJECT_SWIPE.area, 0.6)

        # task delay
        future_finish = sorted([f for f in self.total.get('finish_time') if f is not None])
        logger.info(f'Project finish: {[str(f) for f in future_finish]}')
        if not len(future_finish):
            logger.info('No island project running')
        return future_finish
