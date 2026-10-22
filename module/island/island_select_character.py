"""岛屿角色选择模块。

提供岛屿岗位派遣时的角色选择功能，基于角色网格布局进行状态检测与智能筛选。
通过颜色识别判断角色工作状态、体力值与选中状态，支持 OCR 读取体力数值。
"""
from module.island_select_character.assets import *
from module.base.button import *
from module.base.utils import color_similar, color_similarity_2d, crop, get_color
from module.base.timer import Timer
import numpy as np
from module.ocr.ocr import Digit, DigitCounter
from module.ui.ui import UI
from module.logger import logger


class SelectCharacter(UI):
    """岛屿角色选择与状态识别管理器。

    继承 UI，基于网格布局识别待派遣角色的头像、工作状态、体力数值及选中状态。

    Attributes:
        DISPATCH_STAMINA_DEFAULT (int): 角色派遣默认最低体力门槛。
        select_character_grid (ButtonGrid): 角色选择网格布局。
        unavailable_characters (set): 本轮已判定不可用的角色集合。
        dispatch_stamina_min (int): 当前派遣设定的最低体力门槛。
        character_templates (dict): 角色模板映射字典。
    """
    # 岗位派遣角色的默认最低体力门槛（子模块可按生产消耗覆盖）
    DISPATCH_STAMINA_DEFAULT = 35

    def __init__(self, *args, **kwargs):
        UI.__init__(self, *args, **kwargs)
        self.select_character_grid = ButtonGrid(
            # 头像左上角位于单元格偏移 (33, 45) 处，
            # 与 _cell_button_from_portrait() 的锚点偏移保持一致。
            # 仅识别可靠可读的前两行，第三行不参与网格判定。
            origin=(58, 112),
            delta=(140, 180),
            button_shape=(120, 160),
            grid_shape=(6, 2),
            name="SELECT_CHARACTER_GRID"
        )

        # 本轮已判定不可用的角色（避免同一轮内多次派遣时重复检测）
        self.unavailable_characters = set()
        # 当前模块岗位派遣的最低体力门槛，只用于过滤指定角色；
        # WorkerJuu 体力无限，不参与体力校验。
        self.dispatch_stamina_min = self.DISPATCH_STAMINA_DEFAULT

        # 定义状态检测区域（相对于每个角色按钮）
        self.character_area_relative = (25, 38, 125, 96)
        self.working_area_relative = (15, 92, 105, 121)
        self.stamina_area_relative = (18, 165, 58, 182)
        self.stamina_ocr_area_relative = (0, 165, 80, 184)
        self.selected_area_relative = (86, 26, 119, 42)

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
            # ---- 岛屿新增可派遣角色 ----
            "Anchorage": TEMPLATE_ANCHORAGE,
            "Belfast": TEMPLATE_BELFAST,
            "ChangFeng": TEMPLATE_CHANG_FENG,
            "Mogador": TEMPLATE_MOGADOR,
            "RoyalFortune": TEMPLATE_ROYAL_FORTUNE,
            "DaVinci": TEMPLATE_DAVINCI,
            "Taihou": TEMPLATE_TAIHOU,
        }

    def recognize_all_characters(self, screenshot):
        """识别网格中所有角色的状态。

        Args:
            screenshot (np.ndarray): 游戏画面截图。

        Returns:
            list[dict]: 包含网格位置、按钮区域及各角色状态信息的字典列表。
        """
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
        """只识别指定角色在网格中的位置和状态，跳过其他无关角色。

        Args:
            screenshot (np.ndarray): 游戏画面截图。
            character_names (list[str]): 需要识别的目标角色名称列表。

        Returns:
            list[dict]: 包含匹配角色信息的字典列表。
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
        """识别单个网格单元内角色的完整状态。

        Args:
            screenshot (np.ndarray): 游戏画面截图。
            button (Button): 网格单元按钮对象。
            character_targets (dict[str, Template], optional): 限定的角色模板字典，为 None 时检查所有角色。

        Returns:
            dict | None: 包含角色名、工作中标识、体力值、是否达标及选中状态的字典；未识别到角色则返回 None。
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
        # WorkerJuu 体力无限，视为始终满足；指定角色按岗位体力门槛校验。
        has_stamina = character_name == "WorkerJuu" or stamina >= self.dispatch_stamina_min

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
        """识别指定单元格中的角色身份。

        Args:
            screenshot (np.ndarray): 游戏画面截图。
            button (Button): 网格单元按钮对象。
            character_targets (dict[str, Template], optional): 限定的角色模板字典，为 None 时匹配所有角色。

        Returns:
            str | None: 匹配到的角色名称，低于阈值或无匹配时返回 None。
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
        """检查角色是否处于工作中状态。

        Args:
            screenshot (np.ndarray): 游戏画面截图。
            button (Button): 网格单元按钮对象。

        Returns:
            bool: 角色是否在工作中。
        """
        working_area = self._get_absolute_area(button, self.working_area_relative)
        working_image = crop(screenshot, working_area)

        # 匹配工作中模板
        similarity = TEMPLATE_CHARACTER_WORKING.match(working_image, similarity=0.85)
        return similarity >= 0.85

    def _check_stamina_status(self, screenshot, button):
        """检查角色体力是否充沛（青色判定）。

        Args:
            screenshot (np.ndarray): 游戏画面截图。
            button (Button): 网格单元按钮对象。

        Returns:
            bool: 是否判定为体力充沛。
        """
        stamina_area = self._get_absolute_area(button, (26, 165, 27, 166))
        stamina_color = get_color(screenshot, stamina_area)
        return color_similar(stamina_color, (18.0, 211.0, 186.0), 80)

    def _get_stamina_value(self, screenshot, button):
        """识别角色当前体力值。

        若常规 OCR 解析失败，尝试分别识别当前值与上限值，最后回退至青色进度条长度估算。

        Args:
            screenshot (np.ndarray): 游戏画面截图。
            button (Button): 网格单元按钮对象。

        Returns:
            int: 识别或估算出的体力数值。
        """
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

        # 体力条青色填充段的右边缘恰好压在 "当前/上限" 的斜杠上时，
        # 整段 OCR 会把被破坏的斜杠误识别成数字（如 26/110 读成 267110）。
        # 此时改为在斜杠左右两侧分别识别当前值与上限值。
        current = self._get_stamina_current_ocr(screenshot, button)
        total = self._get_stamina_total_ocr(screenshot, button)
        if current is not None and total and current <= total:
            return current

        return self._get_stamina_percentage_fallback(screenshot, button)

    def _ocr_stamina_area(self, screenshot, button, relative_area, name):
        """对体力区域内的指定子区域执行数字 OCR 识别。

        Args:
            screenshot (np.ndarray): 游戏画面截图。
            button (Button): 网格单元按钮对象。
            relative_area (tuple[int, int, int, int]): 相对体力识别区的坐标范围。
            name (str): OCR 识别器名称。

        Returns:
            int | None: 识别出的数字；解析失败或含非法字符时返回 None。
        """
        area = self._get_absolute_area(button, relative_area)
        ocr = Digit(
            area,
            letter=(255, 255, 255),
            threshold=128,
            name=name,
        )
        try:
            return ocr.ocr(screenshot)
        except (TypeError, ValueError):
            # 区域内可能残留斜杠等字符，int() 解析失败
            return None

    def _get_stamina_current_ocr(self, screenshot, button):
        """在斜杠左侧识别当前体力数值。

        Args:
            screenshot (np.ndarray): 游戏画面截图。
            button (Button): 网格单元按钮对象。

        Returns:
            int | None: 识别出的当前体力数值，超出范围返回 None。
        """
        area = self.stamina_ocr_area_relative
        value = self._ocr_stamina_area(
            screenshot, button,
            (0, area[1], 28, area[3]),
            name='OCR_CHARACTER_STAMINA_CURRENT',
        )
        if isinstance(value, int) and 0 <= value <= 999:
            return value
        return None

    def _get_stamina_total_ocr(self, screenshot, button):
        """在斜杠右侧识别体力上限数值。

        依次尝试不同左边界起点以避开被破坏的斜杠残影。

        Args:
            screenshot (np.ndarray): 游戏画面截图。
            button (Button): 网格单元按钮对象。

        Returns:
            int | None: 识别出的体力上限数值，无有效结果返回 None。
        """
        area = self.stamina_ocr_area_relative
        for left in (28, 30, 32, 34):
            value = self._ocr_stamina_area(
                screenshot, button,
                (left, area[1], area[2], area[3]),
                name='OCR_CHARACTER_STAMINA_TOTAL',
            )
            if isinstance(value, int) and 100 <= value <= 999:
                return value
        return None

    def _get_stamina_percentage_fallback(self, screenshot, button):
        """OCR 失败时通过体力条绿色填充长度估算体力数值。

        Args:
            screenshot (np.ndarray): 游戏画面截图。
            button (Button): 网格单元按钮对象。

        Returns:
            int: 估算出的体力百分比数值（0~100）。
        """
        stamina_area = self._get_absolute_area(button, self.stamina_area_relative)
        stamina_image = crop(screenshot, stamina_area, copy=False)
        similarity = color_similarity_2d(stamina_image, color=(18.0, 211.0, 186.0))
        columns = np.where(np.any(similarity > 175, axis=0))[0]
        if not columns.size:
            return 0
        return min(100, int(round((columns[-1] + 1) / stamina_image.shape[1] * 100)))

    def _check_selected_status(self, screenshot, button):
        """检查角色是否处于已选中状态。

        Args:
            screenshot (np.ndarray): 游戏画面截图。
            button (Button): 网格单元按钮对象。

        Returns:
            bool: 角色是否被选中。
        """
        selected_area = self._get_absolute_area(button, self.selected_area_relative)
        selected_color = get_color(screenshot, selected_area)
        return color_similar(selected_color, (19.0, 182.0, 234.0), 80)

    def _get_absolute_area(self, button, relative_area):
        """将相对于按钮的相对坐标转换为屏幕绝对坐标。

        Args:
            button (Button): 基准按钮对象。
            relative_area (tuple[int, int, int, int]): 相对坐标元组 (x1, y1, x2, y2)。

        Returns:
            tuple[int, int, int, int]: 转换后的屏幕绝对坐标。
        """
        x1 = button.area[0] + relative_area[0]
        y1 = button.area[1] + relative_area[1]
        x2 = button.area[0] + relative_area[2]
        y2 = button.area[1] + relative_area[3]
        return (x1, y1, x2, y2)

    def find_available_characters(self, screenshot):
        """查找当前视野中所有可派遣的角色（非工作中且体力充足）。

        Args:
            screenshot (np.ndarray): 游戏画面截图。

        Returns:
            list[dict]: 可用角色状态信息字典列表。
        """
        all_characters = self.recognize_all_characters(screenshot)
        available = []

        for char_info in all_characters:
            if not char_info["is_working"] and char_info["has_stamina"]:
                available.append(char_info)

        return available

    def find_working_characters(self, screenshot):
        """查找当前视野中所有正在工作中的角色。

        Args:
            screenshot (np.ndarray): 游戏画面截图。

        Returns:
            list[dict]: 工作中角色状态信息字典列表。
        """
        all_characters = self.recognize_all_characters(screenshot)
        working = []

        for char_info in all_characters:
            if char_info["is_working"]:
                working.append(char_info)

        return working

    @staticmethod
    def _normalize_grid_positions(positions):
        """将各种格式的位置输入规范化为 (row, col) 元组列表。

        Args:
            positions: 单个坐标元组、坐标列表或 NumPy 数组。

        Returns:
            list[tuple[int, int]]: 规范化后的二维网格坐标列表。
        """
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
        """迭代指定网格位置并在边界内返回 (row, col, button)。

        Args:
            positions: 待迭代的位置集合。

        Yields:
            tuple[int, int, Button]: 网格行号、列号及对应的按钮对象。
        """
        width, height = self.select_character_grid.grid_shape
        for row, col in self._normalize_grid_positions(positions):
            if row < 0 or col < 0 or row >= width or col >= height:
                logger.warning(f"[岛屿] 角色选择格子位置越界: {(row, col)}")
                continue
            yield row, col, self.select_character_grid[row, col]

    def get_characters_by_positions(self, screenshot, positions, character_names=None):
        """获取指定格子位置的角色状态，支持单个位置或多个位置。

        Args:
            screenshot (np.ndarray): 游戏画面截图。
            positions: 单个或多个网格坐标。
            character_names (list[str], optional): 限定的角色名称列表。

        Returns:
            list[dict]: 匹配到的角色状态信息字典列表。
        """
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
        """获取指定网格位置的角色状态。

        Args:
            screenshot (np.ndarray): 游戏画面截图。
            position: 网格坐标元组 (row, col) 或行号 row。
            col (int, optional): 网格列号（当 position 为行号时传入）。

        Returns:
            dict | None: 该位置的角色状态信息，无角色返回 None。
        """
        if col is not None:
            position = (position, col)
        characters = self.get_characters_by_positions(screenshot, position)
        if characters:
            return characters[0]
        return None

    def is_any_character_selected_by_positions(self, screenshot, positions):
        """检查指定格子位置中是否已有角色被选中。

        Args:
            screenshot (np.ndarray): 游戏画面截图。
            positions: 待检查的网格坐标或坐标列表。

        Returns:
            bool: 是否存在被选中的角色。
        """
        for _, _, button in self._iter_grid_position_buttons(positions):
            if self._check_selected_status(screenshot, button):
                return True
        return False

    def select_character_filter(self):
        """切换角色选择面板中的筛选与排序方式为按体力排序。

        角色页标题会先于底部筛选按钮和弹窗完成渲染。这里以最新截图驱动
        完整状态流程，直到筛选弹窗关闭，而不是点击一次后固定等待并盲点。

        Returns:
            bool: 是否成功完成筛选切换操作。
        """
        self.interval_clear([
            SELECT_CHARACTER_FILTER,
            SELECT_CHARACTER_FILTER_STAMINA,
            SELECT_CHARACTER_FILTER_CONFIRM,
        ])
        filter_clicked = False
        stamina_clicked = False
        confirm_clicked = False
        retry_timer = Timer(2, count=4).start()

        for _ in self.loop(timeout=15, skip_first=False):
            popup_visible = (
                self.appear(SELECT_CHARACTER_FILTER_STAMINA, offset=(10, 10))
                or self.appear(SELECT_CHARACTER_FILTER_CONFIRM, offset=(10, 10))
            )
            if popup_visible:
                if not stamina_clicked:
                    # 弹窗已由确认按钮或体力选项任一命中确认，选项本身颜色会随
                    # 选中状态变化，因此这里直接点击固定位置，避免二次匹配失败。
                    self.device.click(SELECT_CHARACTER_FILTER_STAMINA)
                    stamina_clicked = True
                    retry_timer.reset()
                    continue

                if not confirm_clicked or retry_timer.reached():
                    if self.appear_then_click(SELECT_CHARACTER_FILTER_CONFIRM, offset=(10, 10)):
                        confirm_clicked = True
                        retry_timer.reset()
                continue

            if confirm_clicked:
                return True

            if not filter_clicked or retry_timer.reached():
                if self.appear_then_click(SELECT_CHARACTER_FILTER, offset=(10, 10)):
                    filter_clicked = True
                    retry_timer.reset()

        logger.warning("[岛屿] 角色体力筛选界面未完成，无法继续识别角色")
        return False

    @staticmethod
    def parse_character_filter(character_list):
        """解析角色优先级配置。

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
        """从指定角色列表中选择第一个空闲且体力充沛的角色网格坐标。

        无符合条件的指定角色时回退至 WorkerJuu。

        Args:
            character_list (list[str]): 待筛选的角色优先级列表。

        Returns:
            tuple[int, int] | None: 目标角色的网格坐标 (row, col)，无可用角色则返回 None。
        """
        # 如果传入了空列表，回退到全量匹配
        if not character_list:
            logger.info("[岛屿] 角色列表为空，回退到全量匹配")
            screenshot = self.device.screenshot()
            all_characters = self.recognize_all_characters(screenshot)
            for char_info in all_characters:
                if (not char_info["is_working"] and
                        char_info["has_stamina"]):
                    return char_info["grid_position"]
            return None

        if character_list == ["WorkerJuu"]:
            logger.info("[岛屿] 仅选择 WorkerJuu，先应用体力排序")
            if not self.select_character_filter():
                return None
            for _ in self.loop(timeout=8, skip_first=False):
                position = self.find_specific_character(self.device.image, "WorkerJuu")
                if position is not None:
                    return position
            logger.warning("[岛屿] 体力筛选完成后仍未识别到 WorkerJuu")
            return None

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
        logger.info(f"[岛屿] 工作速度筛选下角色状态: {character_dict}")
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
        logger.info("[岛屿] 应用体力筛选")
        if not self.select_character_filter():
            return None
        screenshot = self.device.screenshot()
        target_characters = self.recognize_target_characters(screenshot, target_names)

        # 构建角色名到状态的映射
        character_dict = {}
        for char_info in target_characters:
            character_dict[char_info["character_name"]] = char_info
        logger.info(f"[岛屿] 体力筛选下角色状态: {character_dict}")
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
            return character_dict["WorkerJuu"]["grid_position"]

        return None

    def find_strict_available_character(self, character_list, min_stamina=35):
        """严格从指定角色列表中寻找空闲且体力达标的角色，不回退 WorkerJuu。

        Args:
            character_list (str | list[str]): 使用 '>' 分隔的字符串或角色名称列表。
            min_stamina (int): 最低体力阈值，默认为 35。

        Returns:
            dict | None: 可点击角色状态信息字典，找不到则返回 None。
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
        logger.info(f"[岛屿] 指定角色状态: {character_dict}")

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
        """尝试点击并选中指定列表中的角色，不回退 WorkerJuu。

        Args:
            character_list (str | list[str]): 角色优先级字符串或列表。
            min_stamina (int): 最低体力阈值，默认为 35。

        Returns:
            bool: 是否成功点击并选择角色。
        """
        char_info = self.find_strict_available_character(character_list, min_stamina=min_stamina)
        if not char_info:
            return False

        row, col = char_info["grid_position"]
        button = self.select_character_grid[row, col]
        self.device.click(button)
        self.device.sleep(0.3)
        return True

    # ============ 滚动查找指定角色（模仿经营模块选角逻辑） ============
    # 角色选择列表滑动区域与惯性消除安全区（与经营模块保持一致）
    CHARACTER_LIST_SCROLL_BOX = (58, 150, 838, 480)
    CHARACTER_LIST_INERTIA_STOP = (462, 477, 473, 577)
    # 角色选择列表全区域模板匹配范围（与经营模块保持一致）
    CHARACTER_LIST_SEARCH_AREA = (55, 139, 878, 463)

    def _swipe_character_list_down(self):
        """短距离向下滑动角色列表，滑动后点击安全区域消除惯性（模仿经营模块）。"""
        self.device.swipe_vector(vector=(0, -200), box=self.CHARACTER_LIST_SCROLL_BOX,
                                 duration=(0.3, 0.5), name="IslandCharSwipe")
        self.device.click(Button(area=(), color=(), button=self.CHARACTER_LIST_INERTIA_STOP, file={'cn': ''}))
        self.device.sleep(1.0)

    def _swipe_character_list_to_top(self):
        """向上滑动角色列表回到顶部，滑动后点击安全区域消除惯性（模仿经营模块）。"""
        self.device.swipe_vector(vector=(0, 500), box=self.CHARACTER_LIST_SCROLL_BOX,
                                 duration=(0.3, 0.5), name="IslandCharSwipeReset")
        self.device.sleep(0.5)
        self.device.click(Button(area=(), color=(), button=self.CHARACTER_LIST_INERTIA_STOP, file={'cn': ''}))
        self.device.sleep(1.0)

    def _find_character_button_in_area(self, screenshot, character_names, area=None):
        """在角色选择列表区域内通过模板匹配定位指定角色。

        与经营模块 _find_best_character 一致，用于网格未命中（滑动错位）时定位角色。

        Args:
            screenshot (np.ndarray): 游戏画面截图。
            character_names (list[str]): 待查找的角色名称列表。
            area (tuple[int, int, int, int], optional): 模板匹配区域，默认为全列表搜索区域。

        Returns:
            tuple[str, Button] | None: 匹配到的角色名与绝对坐标按钮，未找到返回 None。
        """
        if area is None:
            area = self.CHARACTER_LIST_SEARCH_AREA
        area_img = crop(screenshot, area)
        best = (None, None, 0.0)  # (角色名, Button, 相似度)
        for name in character_names:
            template = self.character_templates.get(name)
            if template is None:
                continue
            sim, btn = template.match_result(area_img)
            if sim >= 0.8 and sim > best[2]:
                # 创建新 Button，坐标从裁剪区域偏移回全屏坐标
                old_area = btn.area
                new_area = (old_area[0] + area[0], old_area[1] + area[1],
                            old_area[2] + area[0], old_area[3] + area[1])
                offset_btn = Button(area=new_area, color=btn.color, button=new_area, file=btn.file)
                best = (name, offset_btn, sim)
        if best[0] is not None:
            return best[0], best[1]
        return None

    def _cell_button_from_portrait(self, portrait_button, name=None):
        """以头像模板匹配框为锚点重建角色单元格，返回单元 Button。

        角色列表可处于任意滚动偏移，固定网格行不可靠；
        头像框左上角相对单元格左上角偏移为 (33, 45)，由当前布局实测得出。

        Args:
            portrait_button (Button): 匹配到的头像按钮。
            name (str, optional): 生成的按钮名称。

        Returns:
            Button: 重建的角色单元格按钮对象。
        """
        x0 = portrait_button.area[0] - 33
        y0 = portrait_button.area[1] - 45
        return Button(
            area=(x0, y0, x0 + 120, y0 + 160),
            color=(), button=(x0, y0, x0 + 120, y0 + 160),
            name=name or 'CHARACTER_CELL',
        )

    def _status_from_cell(self, screenshot, row, col, cell_button, character_name=None):
        """读取指定网格单元的角色状态。

        character_name 给定时跳过二次身份识别（用于全区域模板匹配已确认身份的场景）。

        Args:
            screenshot (np.ndarray): 游戏画面截图。
            row (int): 网格行号。
            col (int): 网格列号。
            cell_button (Button): 单元格按钮对象。
            character_name (str, optional): 已知角色名称，传入时跳过身份识别。

        Returns:
            dict | None: 角色状态信息字典，无角色返回 None。
        """
        if character_name is None:
            status = self._recognize_character_status(screenshot, cell_button)
            if not status:
                return None
            return {**status, "grid_position": (row, col), "button_area": cell_button.area}
        return {
            "character_name": character_name,
            "is_working": self._check_working_status(screenshot, cell_button),
            "stamina": self._get_stamina_value(screenshot, cell_button),
            "is_selected": self._check_selected_status(screenshot, cell_button),
            "grid_position": (row, col),
            "button_area": cell_button.area,
        }

    def _check_character_strict(self, char_info, stamina_threshold):
        """严格检查角色是否满足派遣条件（未工作、未选中、体力大于阈值）。

        Args:
            char_info (dict | None): 角色状态信息字典。
            stamina_threshold (int): 最低体力门槛。

        Returns:
            dict | None: 满足条件返回原始状态字典，任一条件不满足返回 None。
        """
        if char_info is None:
            return None
        char_name = char_info.get("character_name")
        if char_info.get("is_working"):
            logger.info(f"[岛屿] {char_name} 正在工作中，不满足派遣条件")
            return None
        if char_info.get("is_selected"):
            logger.info(f"[岛屿] {char_name} 已选中，不满足派遣条件")
            return None
        stamina = char_info.get("stamina", 0)
        if stamina <= stamina_threshold:
            logger.info(f"[岛屿] {char_name} 体力 {stamina} 不大于 {stamina_threshold}，不满足派遣条件")
            return None
        return char_info

    def find_strict_available_character_with_scroll(self, character_list, stamina_threshold=50,
                                                    max_swipes=5, search_area=None):
        """滚动查找指定角色（模仿经营模块的选角逻辑）。

        只接受指定角色且体力大于 stamina_threshold；不切换排序、不回退其他角色。
        找到后返回角色状态字典，未找到或体力不达标返回 None。

        Args:
            character_list: 角色名或 ">" 分隔的优先级字符串。
            stamina_threshold (int): 体力必须大于该阈值。
            max_swipes (int): 最多向下滑动次数。
            search_area: 全区域模板匹配范围，默认 CHARACTER_LIST_SEARCH_AREA。

        Returns:
            dict | None: 可点击角色状态，找不到或体力不达标返回 None。
        """
        characters = self.parse_character_filter(character_list)
        if not characters:
            return None

        # 本轮已判定不可用的角色直接跳过，不再重复检测
        for char_name in characters:
            if char_name in self.unavailable_characters:
                logger.info(f"[岛屿] {char_name} 本轮已判定不可用，跳过检测")
                return None

        # 先回到列表顶部，从头开始搜索
        self._swipe_character_list_to_top()

        for attempt in range(max_swipes):
            screenshot = self.device.screenshot()
            # 1) 优先网格识别：直接获得体力/工作/选中状态
            target_characters = self.recognize_target_characters(screenshot, characters)
            character_dict = {char_info["character_name"]: char_info for char_info in target_characters}
            for char_name in characters:
                char_info = character_dict.get(char_name)
                if char_info:
                    checked = self._check_character_strict(char_info, stamina_threshold)
                    if checked is None:
                        self.unavailable_characters.add(char_name)
                        # 失败退出前回到列表顶部，避免影响下一个岗位的选角视野
                        self._swipe_character_list_to_top()
                    return checked
            # 2) 网格未命中（列表滚动偏移）时，全区域模板匹配定位（模仿经营模块）
            found = self._find_character_button_in_area(screenshot, characters, area=search_area)
            if found:
                char_name, portrait_button = found
                # 以头像匹配框为锚点重建单元格，读取任意滚动偏移下的状态
                cell_button = self._cell_button_from_portrait(portrait_button, name=char_name)
                row = round((cell_button.area[1] - self.select_character_grid.origin[1])
                            / self.select_character_grid.delta[1])
                col = round((cell_button.area[0] - self.select_character_grid.origin[0])
                            / self.select_character_grid.delta[0])
                # 复核身份：避免模板误配到相似角色
                verify_image = crop(screenshot, self._get_absolute_area(cell_button, self.character_area_relative))
                if not self.character_templates[char_name].match(verify_image, similarity=0.8):
                    logger.warning(f"[岛屿] {char_name} 单元格身份复核不通过，继续向下滑动搜索")
                    continue
                char_info = self._status_from_cell(
                    screenshot, row, col, cell_button, character_name=char_name
                )
                # 点击目标直接用头像匹配框，避免固定网格在滚动偏移下点错位置
                char_info["button"] = portrait_button
                # 选中状态检测以重建单元格为基准（头像框与单元格偏移不同）
                char_info["cell_button"] = cell_button
                checked = self._check_character_strict(char_info, stamina_threshold)
                if checked is None:
                    self.unavailable_characters.add(char_name)
                    # 失败退出前回到列表顶部，避免影响下一个岗位的选角视野
                    self._swipe_character_list_to_top()
                return checked
            # 3) 当前视野没有目标角色，向下滑动继续搜索
            self._swipe_character_list_down()

        logger.info(f"[岛屿] 角色列表滚动 {max_swipes} 次后仍未找到: {characters}")
        self.unavailable_characters.update(characters)
        # 失败退出前回到列表顶部，避免影响下一个岗位的选角视野
        self._swipe_character_list_to_top()
        return None

    def select_specific_character_with_scroll(self, character_list, stamina_threshold=50, max_swipes=5):
        """只选择指定角色（支持向下滚动查找，模仿经营模块选角逻辑）。

        体力不达标或未找到时返回 False，不切换排序、不回退其他角色、不重复尝试。
        点击后校验是否选中，最多点击 5 次（纯计数有限循环）。

        Args:
            character_list (str | list[str]): 角色优先级字符串或列表。
            stamina_threshold (int): 体力门槛，必须大于该值。
            max_swipes (int): 最多向下滑动次数，默认为 5。

        Returns:
            bool: 成功选中指定角色返回 True，否则返回 False。
        """
        char_info = self.find_strict_available_character_with_scroll(
            character_list, stamina_threshold=stamina_threshold, max_swipes=max_swipes
        )
        if not char_info:
            return False

        row, col = char_info["grid_position"]
        # 滚动回退路径携带头像匹配框作为点击目标，网格路径使用固定网格；
        # 选中状态检测以重建单元格为基准，避免头像框偏移导致确认失败
        button = char_info.get("button") or self.select_character_grid[row, col]
        status_button = char_info.get("cell_button") or button
        for attempt in range(5):
            screenshot = self.device.screenshot()
            if self._check_selected_status(screenshot, status_button):
                return True
            self.device.click(button)
            self.device.sleep(0.3)
        return False

    def find_specific_character(self, screenshot, character_name="WorkerJuu"):
        """查找指定角色的位置信息，只检查目标角色的模板，不做全量匹配。

        Args:
            screenshot (np.ndarray): 游戏画面截图。
            character_name (str): 目标角色名称，默认为 'WorkerJuu'。

        Returns:
            tuple[int, int] | None: 角色的网格坐标 (row, col)，未找到返回 None。
        """
        target_characters = self.recognize_target_characters(screenshot, [character_name])
        for char_info in target_characters:
            if char_info["character_name"] == character_name:
                return char_info["grid_position"]
        return None

    def select_character(self, character_list="WorkerJuu"):
        """按照角色列表优先级选择角色。

        如果没有可选角色则选择工作啾。

        Args:
            character_list (str | list[str]): 角色列表字符串，用">"分隔，如"Cheshire > YingSwei"，也可以传入单个角色名。

        Returns:
            bool: 成功选择角色返回 True，无角色可选返回 False。
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
