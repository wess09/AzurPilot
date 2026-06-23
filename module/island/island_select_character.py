from module.island_select_character.assets import *
from module.base.button import *
from module.base.utils import color_similar, color_similarity_2d, crop, get_color
import numpy as np
from module.ocr.ocr import DigitCounter
from module.ui.ui import UI
from module.logger import logger


class SelectCharacter(UI):
    def __init__(self, *args, **kwargs):
        UI.__init__(self, *args, **kwargs)
        self.select_character_grid = ButtonGrid(
            origin=(58, 141),
            delta=(140, 180),
            button_shape=(120, 160),
            grid_shape=(6, 2),
            name="SELECT_CHARACTER_GRID"
        )

        # 定义状态检测区域（相对于每个角色按钮）
        self.character_area_relative = (25, 10, 125, 72)
        self.working_area_relative = (15, 65, 105, 95)
        self.stamina_area_relative = (18, 139, 58, 152)
        self.stamina_ocr_area_relative = (0, 136, 80, 155)
        self.selected_area_relative = (86, 1, 119, 12)

        # 角色模板映射
        self.character_templates = {
            "WorkerJuu": TEMPLATE_WORKERJUU,
            "NewJersey": TEMPLATE_NEWJERSEY,
            "Tashkent": TEMPLATE_TASHKENT,
            "YingSwei": TEMPLATE_YINGSWEI,
            "Saratoga": TEMPLATE_SARATOGA,
            "Akashi": TEMPLATE_AKASHI,
            "LeMalin": TEMPLATE_LEMALIN,
            "Shimakaze": TEMPLATE_SHIMAKAZE,
            "Amagi_chan": TEMPLATE_AMAGI_CHAN,
            "Cheshire": TEMPLATE_CHESHIRE,
            "Unicorn": TEMPLATE_UNICORN,
            "ChaoHo": TEMPLATE_CHAO_HO,
            "ChenHai": TEMPLATE_CHEN_HAI,
            "WilliamDPorter": TEMPLATE_WILLIAM_D_PORTER,
            "Helena": TEMPLATE_HELENA,
            "Friedrich": TEMPLATE_FRIEDRICH,
            "Atago": TEMPLATE_ATAGO,
            # ---- 版本更新新增角色 ----
            "Yixian": TEMPLATE_YIXIAN,
            "August": TEMPLATE_AUGUST,
            "Eugen": TEMPLATE_EUGEN,
            "Hood": TEMPLATE_HOOD,
            "Javelin": TEMPLATE_JAVELIN,
            "Laffey": TEMPLATE_LAFFEY,
            "Explorer": TEMPLATE_EXPLORER,
            "Navigator": TEMPLATE_NAVIGATOR,
            "OceanCrosser": TEMPLATE_OCEAN_CROSSER,
            "FeiYun": TEMPLATE_FEI_YUN,
            "Takao": TEMPLATE_TAKAO,
        }

    def recognize_all_characters(self, screenshot):
        """识别网格中所有角色的状态"""
        results = []

        for row, col, button in self.select_character_grid.generate():
            # 获取角色按钮区域
            character_status = self._recognize_character_status(screenshot, button)
            if character_status:
                results.append({
                    "grid_position": (row, col),
                    "button_area": button.area,
                    **character_status
                })

        return results

    def recognize_target_characters(self, screenshot, character_names):
        """
        只识别指定角色在网格中的位置和状态，跳过其他角色

        Args:
            screenshot: 游戏截图
            character_names (list): 需要识别的角色名列表

        Returns:
            list: 包含匹配角色信息的字典列表
        """
        results = []

        # 过滤出需要识别的模板子集
        target_templates = {
            name: self.character_templates[name]
            for name in character_names
            if name in self.character_templates
        }

        if not target_templates:
            return results

        remaining_templates = target_templates.copy()
        for row, col, button in self.select_character_grid.generate():
            character_status = self._recognize_character_status(
                screenshot, button, character_targets=remaining_templates
            )
            if character_status:
                remaining_templates.pop(character_status["character_name"], None)
                results.append({
                    "grid_position": (row, col),
                    "button_area": button.area,
                    **character_status
                })
                if not remaining_templates:
                    break

        return results

    def _recognize_character_status(self, screenshot, button, character_targets=None):
        """识别单个角色的状态

        Args:
            screenshot: 游戏截图
            button: 角色按钮
            character_targets (dict, optional): 限定的角色模板字典 {name: template}，
                                                为 None 时检查所有角色
        """
        # 1. 识别角色身份
        character_name = self._recognize_character_identity(
            screenshot, button, character_targets=character_targets
        )
        if not character_name:
            return None  # 该位置没有角色

        # 2. 识别是否工作中
        is_working = self._check_working_status(screenshot, button)

        # 3. 识别当前体力值
        stamina = self._get_stamina_value(screenshot, button)
        has_stamina = stamina >= 35

        # 4. 识别是否已选中
        is_selected = self._check_selected_status(screenshot, button)

        return {
            "character_name": character_name,
            "is_working": is_working,
            "stamina": stamina,
            "has_stamina": has_stamina,
            "is_selected": is_selected
        }

    def _recognize_character_identity(self, screenshot, button, character_targets=None):
        """识别角色身份

        Args:
            screenshot: 游戏截图
            button: 角色按钮
            character_targets (dict, optional): 限定的角色模板字典 {name: template}，
                                                为 None 时检查所有角色
        """
        # 获取角色识别区域
        char_area = self._get_absolute_area(button, self.character_area_relative)
        char_image = crop(screenshot, char_area)

        # 确定要匹配的模板集合
        templates_to_check = character_targets if character_targets is not None else self.character_templates

        # 遍历目标角色模板进行匹配
        best_match = None
        best_similarity = 0.0

        for char_name, template in templates_to_check.items():
            similarity = template.match(char_image, similarity=0.8)
            if similarity > best_similarity and similarity >= 0.8:
                best_similarity = similarity
                best_match = char_name

        return best_match

    def _check_working_status(self, screenshot, button):
        """检查是否工作中"""
        working_area = self._get_absolute_area(button, self.working_area_relative)
        working_image = crop(screenshot, working_area)

        # 匹配工作中模板
        similarity = TEMPLATE_CHARACTER_WORKING.match(working_image, similarity=0.85)
        return similarity >= 0.85

    def _check_stamina_status(self, screenshot, button):
        """检查体力是否充沛"""
        stamina_area = self._get_absolute_area(button, (26, 139, 27, 140))
        stamina_color = get_color(screenshot, stamina_area)
        return color_similar(stamina_color, (18.0, 211.0, 186.0), 80)

    def _get_stamina_value(self, screenshot, button):
        """识别角色当前体力值。"""
        stamina_area = self._get_absolute_area(button, self.stamina_ocr_area_relative)
        ocr = DigitCounter(
            stamina_area,
            letter=(255, 255, 255),
            threshold=128,
            name='OCR_CHARACTER_STAMINA',
        )
        current, _, total = ocr.ocr(screenshot)
        if total:
            return current

        return self._get_stamina_percentage_fallback(screenshot, button)

    def _get_stamina_percentage_fallback(self, screenshot, button):
        """OCR 失败时用体力条绿色长度估算体力。"""
        stamina_area = self._get_absolute_area(button, self.stamina_area_relative)
        stamina_image = crop(screenshot, stamina_area, copy=False)
        similarity = color_similarity_2d(stamina_image, color=(18.0, 211.0, 186.0))
        columns = np.where(np.any(similarity > 175, axis=0))[0]
        if not columns.size:
            return 0
        return min(100, int(round((columns[-1] + 1) / stamina_image.shape[1] * 100)))

    def _check_selected_status(self, screenshot, button):
        """检查是否已选中"""
        selected_area = self._get_absolute_area(button, self.selected_area_relative)
        selected_color = get_color(screenshot, selected_area)
        return color_similar(selected_color, (19.0, 182.0, 234.0), 80)

    def _get_absolute_area(self, button, relative_area):
        """将相对坐标转换为绝对坐标"""
        x1 = button.area[0] + relative_area[0]
        y1 = button.area[1] + relative_area[1]
        x2 = button.area[0] + relative_area[2]
        y2 = button.area[1] + relative_area[3]
        return (x1, y1, x2, y2)

    def find_available_characters(self, screenshot):
        """查找可用的角色（非工作中、体力充沛）"""
        all_characters = self.recognize_all_characters(screenshot)
        available = []

        for char_info in all_characters:
            if not char_info["is_working"] and char_info["has_stamina"]:
                available.append(char_info)

        return available

    def find_working_characters(self, screenshot):
        """查找工作中的角色"""
        all_characters = self.recognize_all_characters(screenshot)
        working = []

        for char_info in all_characters:
            if char_info["is_working"]:
                working.append(char_info)

        return working

    @staticmethod
    def _normalize_grid_positions(positions):
        if positions is None:
            return []

        if isinstance(positions, np.ndarray):
            positions = positions.tolist()

        if (
                isinstance(positions, (tuple, list))
                and len(positions) == 2
                and all(isinstance(value, (int, np.integer)) for value in positions)
        ):
            return [(int(positions[0]), int(positions[1]))]

        normalized = []
        for position in positions:
            if isinstance(position, np.ndarray):
                position = position.tolist()
            if not isinstance(position, (tuple, list)) or len(position) != 2:
                continue
            row, col = position
            try:
                normalized.append((int(row), int(col)))
            except (TypeError, ValueError):
                continue
        return normalized

    def _iter_grid_position_buttons(self, positions):
        width, height = self.select_character_grid.grid_shape
        for row, col in self._normalize_grid_positions(positions):
            if row < 0 or col < 0 or row >= width or col >= height:
                logger.warning(f"角色选择格子位置越界: {(row, col)}")
                continue
            yield row, col, self.select_character_grid[row, col]

    def get_characters_by_positions(self, screenshot, positions, character_names=None):
        """获取指定格子位置的角色状态，支持单个位置或多个位置。"""
        results = []
        if character_names is None:
            character_targets = None
        else:
            character_targets = {
                name: self.character_templates[name]
                for name in character_names
                if name in self.character_templates
            }
            if not character_targets:
                return results

        for row, col, button in self._iter_grid_position_buttons(positions):
            character_status = self._recognize_character_status(
                screenshot, button, character_targets=character_targets
            )
            if character_status:
                results.append({
                    "grid_position": (row, col),
                    "button_area": button.area,
                    **character_status
                })

        return results

    def get_character_by_position(self, screenshot, position, col=None):
        """获取指定网格位置的字符状态"""
        if col is not None:
            position = (position, col)
        characters = self.get_characters_by_positions(screenshot, position)
        if characters:
            return characters[0]
        return None

    def is_any_character_selected_by_positions(self, screenshot, positions):
        """检查指定格子位置中是否已有角色被选中。"""
        for _, _, button in self._iter_grid_position_buttons(positions):
            if self._check_selected_status(screenshot, button):
                return True
        return False

    def select_character_filter(self):
        if self.appear_then_click(SELECT_CHARACTER_FILTER):
            self.device.sleep(0.5)
            self.device.click(SELECT_CHARACTER_FILTER_STAMINA)
            self.device.sleep(0.5)
            self.device.click(SELECT_CHARACTER_FILTER_CONFIRM)
            self.device.sleep(0.5)
            return True
        return False

    @staticmethod
    def parse_character_filter(character_list):
        """
        解析角色优先级配置。

        Args:
            character_list: 使用 > 分隔的字符串，或角色名列表。

        Returns:
            list[str]: 去除空项后的角色名列表，保留原始顺序。
        """
        if isinstance(character_list, str):
            return [char.strip() for char in character_list.split(">") if char.strip()]
        if character_list is None:
            return []
        return [str(char).strip() for char in character_list if str(char).strip()]

    def _select_first_available_character(self, character_list):
        """
        从指定角色列表中选择第一个空闲且体力充沛的角色
        如果无可选角色则选择WorkerJuu

        Returns:
            tuple: (row, col) 或 None
        """
        # 如果传入了空列表，回退到全量匹配
        if not character_list:
            logger.info("角色列表为空，回退到全量匹配")
            screenshot = self.device.screenshot()
            all_characters = self.recognize_all_characters(screenshot)
            for char_info in all_characters:
                if (not char_info["is_working"] and
                        char_info["has_stamina"]):
                    return char_info["grid_position"]
            return None

        if character_list == ["WorkerJuu"]:
            logger.info("仅选择 WorkerJuu，先应用体力排序")
            if not self.select_character_filter():
                return None
            screenshot = self.device.screenshot()
            return self.find_specific_character(screenshot, "WorkerJuu")

        # 计算需要识别的角色集合（包含列表角色+最终回退的WorkerJuu）
        target_names = list(character_list)
        if "WorkerJuu" not in target_names:
            target_names.append("WorkerJuu")

        screenshot = self.device.screenshot()
        target_characters = self.recognize_target_characters(screenshot, target_names)

        # 构建角色名到状态的映射
        character_dict = {}
        for char_info in target_characters:
            character_dict[char_info["character_name"]] = char_info
        logger.info(f"工作速度筛选下角色状态: {character_dict}")
        # 优先按列表顺序检查指定角色
        for char_name in character_list:
            if char_name in character_dict:
                char_info = character_dict[char_name]
                # 检查角色状态和配置可用性
                if (not char_info["is_working"] and
                        char_info["has_stamina"]
                        ):
                    return char_info["grid_position"]
        # 应用体力筛选
        logger.info("应用体力筛选")
        if not self.select_character_filter():
            return None
        screenshot = self.device.screenshot()
        target_characters = self.recognize_target_characters(screenshot, target_names)

        # 构建角色名到状态的映射
        character_dict = {}
        for char_info in target_characters:
            character_dict[char_info["character_name"]] = char_info
        logger.info(f"体力筛选下角色状态: {character_dict}")
        # 优先按列表顺序检查指定角色
        for char_name in character_list:
            if char_name in character_dict:
                char_info = character_dict[char_name]
                # 检查角色状态和配置可用性
                if (not char_info["is_working"] and
                        char_info["has_stamina"]
                        ):
                    return char_info["grid_position"]

        # 如果没有找到可用角色，查找WorkerJuu
        if "WorkerJuu" in character_dict:
            worker_info = character_dict["WorkerJuu"]
            return worker_info["grid_position"]

        return None

    def find_strict_available_character(self, character_list, min_stamina=35):
        """
        只从指定角色中寻找可选角色，不回退 WorkerJuu。

        Args:
            character_list: 使用 > 分隔的字符串，或角色名列表。
            min_stamina: 最低体力阈值。

        Returns:
            dict | None: 可点击角色状态，找不到则返回 None。
        """
        characters = self.parse_character_filter(character_list)
        if not characters:
            return None

        screenshot = self.device.screenshot()
        target_characters = self.recognize_target_characters(screenshot, characters)
        character_dict = {
            char_info["character_name"]: char_info
            for char_info in target_characters
        }
        logger.info(f"指定角色状态: {character_dict}")

        for char_name in characters:
            char_info = character_dict.get(char_name)
            if not char_info:
                continue
            if char_info["is_working"] or char_info["is_selected"]:
                continue
            if char_info.get("stamina", 0) < min_stamina:
                continue
            return char_info

        return None

    def select_specific_character(self, character_list, min_stamina=35):
        """
        只尝试选择指定角色，不回退 WorkerJuu。

        Returns:
            bool: 成功选择角色返回 True，否则返回 False。
        """
        char_info = self.find_strict_available_character(character_list, min_stamina=min_stamina)
        if not char_info:
            return False

        row, col = char_info["grid_position"]
        button = self.select_character_grid[row, col]
        self.device.click(button)
        self.device.sleep(0.3)
        return True

    def find_specific_character(self, screenshot, character_name="WorkerJuu"):
        """查找指定角色的位置信息，只检查目标角色的模板，不做全量匹配"""
        target_characters = self.recognize_target_characters(screenshot, [character_name])
        for char_info in target_characters:
            if char_info["character_name"] == character_name:
                return char_info["grid_position"]
        return None

    def select_character(self, character_list="WorkerJuu"):
        """
        按照角色列表优先级选择角色
        如果没有可选角色则选择工作啾

        Args:
            character_list: 角色列表字符串，用">"分隔，如"Cheshire > YingSwei"
                          也可以传入单个角色名，如"Cheshire"

        Returns:
            bool: 成功选择角色返回True，无角色可选返回False
        """
        # 解析角色列表
        characters = self.parse_character_filter(character_list)
        if not characters:
            characters = ["WorkerJuu"]

        position = self._select_first_available_character(characters)

        # 如果没有找到任何可用角色
        if position is None:
            return False

        row, col = position
        button = self.select_character_grid[row, col]

        # 尝试点击选择，最多5次
        max_attempts = 5
        attempts = 0
        target_positions = [(row, col)]

        while attempts < max_attempts:
            screenshot = self.device.screenshot()

            if self.is_any_character_selected_by_positions(screenshot, target_positions):
                return True
            else:
                self.device.click(button)

            self.device.sleep(0.3)
            attempts += 1

        return False
