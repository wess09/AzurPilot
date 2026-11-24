"""装备码（配装码）解析与应用模块。
支持从游戏内读取 Base64 编码的装备方案码，
并通过 UI 自动化将方案中指定的装备应用到舰船上。"""

import re

import cv2
import numpy as np
import yaml

from module.base.timer import Timer
from module.equipment.assets import *
from module.exception import EmulatorNotRunningError, RequestHumanTakeover
from module.logger import logger
from module.retire.assets import TEMPLATE_BOGUE, TEMPLATE_HERMES, TEMPLATE_RANGER, TEMPLATE_LANGLEY
from module.storage.assets import EQUIPMENT_FULL
from module.storage.storage import StorageHandler

EMPTY_CODE = "MC8wLzAvMC8wXDA="
EQUIPMENT_CODE_PATTERN = re.compile(r'[A-Za-z0-9+/=]{%d,}' % len(EMPTY_CODE))
U2_CONTROL_METHODS = {'uiautomator2', 'minitouch', 'MaaTouch'}
EQUIPMENT_PREVIEW_EMPTY = [
    EQUIPMENT_CODE_EQUIP_0,
    EQUIPMENT_CODE_EQUIP_1,
    EQUIPMENT_CODE_EQUIP_2,
    EQUIPMENT_CODE_EQUIP_3,
    EQUIPMENT_CODE_EQUIP_4,
    EQUIPMENT_CODE_EQUIP_5,
]
EQUIPMENT_PREVIEW_OCCUPIED = [
    EQUIPMENT_PREVIEW_SLOT_0_STAR,
    EQUIPMENT_PREVIEW_SLOT_1_STAR,
    EQUIPMENT_PREVIEW_SLOT_2_STAR,
    EQUIPMENT_PREVIEW_SLOT_3_STAR,
    EQUIPMENT_PREVIEW_SLOT_4_STAR,
]


class EquipmentCodeHandler(StorageHandler):
    """装备码（配装码）处理器。

    支持在舰船装备码界面导入、导出及应用 Base64 编码的装备方案，
    并与用户配置或外部存储交互。

    Attributes:
        last_code (str): 上一次暂存的装备码字符串。
    """
    last_code: str = None

    @property
    def equipment_code_config_key(self):
        """获取当前任务的装备码配置键，子类可重写。"""
        return None

    @property
    def equipment_code_export_to_config(self):
        """判断是否需要将导出的装备码持久化写入配置中。"""
        if self.equipment_code_config_key:
            return True
        return getattr(self.config, 'EquipmentCode_ExportToConfig', False)

    def _code_config_load(self):
        """加载并解析 YAML 格式的装备码配置映射字典。

        Returns:
            dict: 舰船名称到装备码的映射字典。

        Raises:
            RequestHumanTakeover: 装备码配置格式错误时抛出。
        """
        key = self.equipment_code_config_key
        if key:
            raw = self.config.cross_get(keys=key)
        else:
            raw = getattr(self.config, 'EquipmentCode_Config', '')

        config = {}
        try:
            for item in yaml.safe_load_all(raw or ''):
                if item is None:
                    continue
                if not isinstance(item, dict):
                    raise ValueError('装备码配置必须是名称到装备码的映射')
                config.update(item)
        except (yaml.YAMLError, TypeError, ValueError) as exc:
            # 不能把损坏的配置当成空配置，随后自动保存会覆盖其余方案。
            raise RequestHumanTakeover('装备码配置格式错误，请检查配置后再换船') from exc
        return config

    def _code_config_save(self, config):
        """将装备码配置映射字典序列化并保存到对应配置项。

        Args:
            config (dict): 舰船名称到装备码的映射字典。

        Returns:
            bool: 保存成功返回 True，无配置目标返回 False。
        """
        value = yaml.safe_dump(config)
        key = self.equipment_code_config_key
        if key:
            self.config.cross_set(keys=key, value=value)
        elif hasattr(self.config, 'EquipmentCode_Config'):
            self.config.EquipmentCode_Config = value
        else:
            logger.warning("无装备码配置目标，跳过保存")
            return False
        return True

    def equipment_code_supported(self):
        """检测当前模拟器控制方式是否支持装备码自动输入（需 uiautomator2 系列）。

        Returns:
            bool: 支持返回 True，否则返回 False。
        """
        method = self.config.Emulator_ControlMethod
        if method in U2_CONTROL_METHODS:
            return True

        logger.warning(
            f"装备码需要基于 uiautomator2 的控制方式，"
            f"当前控制方式为 {method}，跳过装备更换"
        )
        return False

    def get_code(self, name):
        """获取指定舰船名称已保存的装备码。

        Args:
            name (str): 舰船名称或类型标识。

        Returns:
            str | None: 装备码字符串，若未配置或格式无效返回 None。
        """
        config = self._code_config_load()
        code = config.get(name)
        if code is None or isinstance(code, str) and not code.strip():
            logger.info(f"[装备-代码] 尚未配置 {name} 的装备代码")
            return None
        if not self._is_equipment_code(code):
            logger.warning(f"[装备-代码] {name} 的装备代码格式无效")
            return None
        return code.strip().strip('\'\"')

    def set_code(self, name, code):
        """保存指定舰船名称的装备码到配置。

        Args:
            name (str): 舰船名称或类型标识。
            code (str): 待保存的装备码。

        Returns:
            bool: 保存成功返回 True，格式非法或异常返回 False。

        Raises:
            EmulatorNotRunningError: 模拟器未运行时抛出。
            RequestHumanTakeover: 遭遇严重错误需人工介入时抛出。
        """
        if not self._is_equipment_code(code):
            return False
        config = self._code_config_load()
        try:
            config.update({name: code})
            return self._code_config_save(config)
        except (EmulatorNotRunningError, RequestHumanTakeover):
            raise
        except Exception:
            logger.error("设置装备码配置失败")
            return False

    def current_ship(self):
        """识别当前舰船详情界面的舰船种类。

        当前主要支持常见低耗轻航（博格、竞技神、突击者、兰利）模板识别。

        Returns:
            str: 识别到的舰船名称标识，未知舰船默认返回 'DD'。

        Pages:
            in: equipment_code
        """
        for _ in self.loop():
            if not self.appear(EMPTY_SHIP_R):
                break
        if TEMPLATE_BOGUE.match(self.device.image, scaling=1.46):  # 图像存在轻微旋转
            logger.info("检测到博格")
            return 'bogue'
        elif TEMPLATE_HERMES.match(self.device.image, scaling=124 / 89):
            logger.info("检测到竞技神")
            return 'hermes'
        elif TEMPLATE_RANGER.match(self.device.image, scaling=4 / 3):
            logger.info("检测到突击者")
            return 'ranger'
        elif TEMPLATE_LANGLEY.match(self.device.image, scaling=25 / 21):
            logger.info("检测到兰利")
            return 'langley'
        else:
            logger.warning("检测到未知舰船，假设为驱逐舰")
            return 'DD'

    def _code_enter(self):
        """从舰船详情界面点击进入装备码界面。

        Pages:
            in: ship_detail
            out: equipment_code（EQUIPMENT_CODE_PAGE_CHECK）
        """
        for _ in self.loop():
            if self.appear(EQUIPMENT_CODE_PAGE_CHECK, offset=(5, 5)):
                break

            if self.appear_then_click(EQUIPMENT_CODE_ENTRANCE, offset=(5, 5), interval=1):
                continue

    def _code_exit(self):
        """退出装备码界面，返回舰船详情界面。

        Pages:
            in: equipment_code
            out: ship_detail
        """
        self.ui_back(check_button=EQUIPMENT_CODE_ENTRANCE)

    def is_code_preview_empty(self):
        """检测当前装备码预览区域所有槽位是否为空。

        Returns:
            bool: 所有槽位均为空返回 True，否则返回 False。
        """
        # 只有所有可用槽位都正向命中空槽，才能确认预览已清空。
        return all(
            self.appear(button, offset=(5, 5))
            for button in EQUIPMENT_PREVIEW_EMPTY[:5]
        ) and (
            self.appear(EQUIPMENT_CODE_EQUIP_5_LOCKED, offset=(5, 5))
            or self.appear(EQUIPMENT_CODE_EQUIP_5, offset=(5, 5))
        )

    def _code_preview_slot_occupied(self, button):
        """检测指定装备预览槽位是否有装备占用。

        Args:
            button (Button): 待检测的槽位星级模板按钮。

        Returns:
            bool: 槽位被占用返回 True，否则返回 False。
        """
        return button.match_luma(self.device.image, offset=(2, 2), similarity=0.85)

    def _code_special_equip_occupied(self):
        """检测特殊装备（兵装）槽位是否有装备占用。

        Returns:
            bool: 特殊装备槽位有装备返回 True，否则返回 False。
        """
        x1, y1, x2, y2 = EQUIPMENT_CODE_EQUIP_5.area
        image = self.device.image[y1:y2, x1:x2]
        hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
        quality_color = np.zeros(hsv.shape[:2], dtype=bool)
        for lower, upper in (
            ((15, 100, 180), (25, 170, 250)),   # 金色
            ((95, 120, 175), (106, 180, 240)),  # 蓝色
            ((118, 65, 145), (130, 125, 210)),  # 紫色
        ):
            quality_color |= cv2.inRange(hsv, lower, upper) > 0

        rows, columns = np.ogrid[:quality_color.shape[0], :quality_color.shape[1]]
        delta_x = columns - 46
        delta_y = rows - 40
        distance_squared = delta_x ** 2 + delta_y ** 2
        # 挖空中心以避开装备贴图，只采集槽位外围的品质背景色。
        annulus = (distance_squared >= 24 ** 2) & (distance_squared <= 32 ** 2)
        angles = (np.arctan2(delta_y, delta_x) + 2 * np.pi) % (2 * np.pi)
        sectors = np.floor(angles / (np.pi / 4)).astype(np.int8)
        ratios = [
            float(np.mean(quality_color[annulus & (sectors == index)]))
            for index in range(8)
        ]
        # 允许贴图随机遮挡部分圆环，只要求颜色最完整的四个扇区稳定命中。
        return float(np.mean(sorted(ratios)[-4:])) >= 0.65

    def is_code_preview_loaded(self):
        """检测装备码预览是否已经加载并显示装备。

        Returns:
            bool: 预览已加载返回 True，尚未加载或全空返回 False。
        """
        occupied_states = []
        for empty, occupied in zip(EQUIPMENT_PREVIEW_EMPTY, EQUIPMENT_PREVIEW_OCCUPIED):
            empty_appear = self.appear(empty, offset=(5, 5))
            occupied_appear = self._code_preview_slot_occupied(occupied)

            # 前五槽共同确认当前确实是装备预览；未知或歧义状态均继续等待。
            if empty_appear == occupied_appear:
                return False
            occupied_states.append(occupied_appear)

        if any(occupied_states):
            return True

        # 只有前五槽均可信且为空时，才需要判断容易受贴图影响的第六槽。
        if self.appear(EQUIPMENT_CODE_EQUIP_5_LOCKED, offset=(5, 5)):
            return False
        if self.appear(EQUIPMENT_CODE_EQUIP_5, offset=(5, 5)):
            return False
        return self._code_special_equip_occupied()

    def _code_preview_clear(self):
        """点击清空预览区域已有的装备方案。

        Returns:
            bool: 成功清空返回 True，超时返回 False。
        """
        for _ in self.loop(timeout=2):
            if self.is_code_preview_empty():
                return True

            if self.appear_then_click(EQUIPMENT_CODE_CLEAR, offset=(5, 5), interval=1):
                continue
        else:
            return False

    @staticmethod
    def _adb_input_text_escape(text):
        """对 ADB input text 命令中的特殊字符进行转义。

        Args:
            text (str): 原始待输入文本。

        Returns:
            str: 转义后的文本。
        """
        text = str(text).replace('%', '%s')
        for char in ['\\', '"', "'", '`', '$', '&', '|', '<', '>', ';', '(', ')', '*']:
            text = text.replace(char, f'\\{char}')
        return text

    def _code_input_adb(self, code):
        """通过 ADB Shell 命令向文本框输入装备码文本。

        Args:
            code (str): 装备码文本。

        Returns:
            bool: 输入成功返回 True，失败返回 False。
        """
        try:
            text = self._adb_input_text_escape(code)
            clear_keys = ' '.join(['KEYCODE_DEL'] * (len(code) + 10))
            self.device.adb_shell(f'input keyevent KEYCODE_MOVE_END {clear_keys}', timeout=5)
            self.device.adb_shell(f'input text {text}', timeout=5)
            self.device.adb_shell('input keyevent KEYCODE_ENTER', timeout=1)
            logger.info("通过 ADB 输入装备码")
            return True
        except (EmulatorNotRunningError, RequestHumanTakeover):
            raise
        except Exception as e:
            logger.warning(f"通过 ADB 输入装备码失败: {e}")
            return False

    def _code_wait_preview_loaded(self, wait_for_keyboard=False):
        """等待装备码预览加载完成。

        Args:
            wait_for_keyboard (bool): 使用设备输入后端时等待键盘收起。

        Returns:
            bool: 成功加载预览返回 True，超时返回 False。
        """
        for _ in self.loop(timeout=10, skip_first=False):
            if wait_for_keyboard and self.device.current_ime_adb()[1]:
                continue
            # End：正向退出判断必须位于点击操作之前。
            if self.is_code_preview_loaded():
                return True

            if self.appear_then_click(EQUIPMENT_CODE_ENTER, offset=(5, 5), interval=3):
                continue

        return False

    def _code_input(self, code):
        """尝试多种输入后端将装备码输入到输入框中并等待预览加载。

        Args:
            code (str): 装备码文本。

        Returns:
            bool: 成功输入并加载预览返回 True，否则返回 False。
        """
        logger.info(f"代码输入: {code}")
        for _ in range(2):
            click_timer = Timer(1, count=3)
            textbox_clicked = False
            for _ in self.loop(timeout=5):
                if textbox_clicked and self._code_input_adb(code):
                    break
                if click_timer.reached_and_reset():
                    self.device.click(EQUIPMENT_CODE_TEXTBOX)
                    textbox_clicked = True
            else:
                continue

            if self._code_wait_preview_loaded():
                return True

        self.device.input_text_fastinput_ime(code, EQUIPMENT_CODE_TEXTBOX)
        if self._code_wait_preview_loaded(wait_for_keyboard=True):
            return True

        logger.warning("装备码加载失败")
        return False

    def _code_confirm(self):
        """确认应用装备码并退出装备码界面。

        Returns:
            bool: 成功应用返回 True，仓库已满或超时返回 False。
        """
        logger.info("代码应用")
        for _ in self.loop(timeout=10):
            if self.appear(EQUIPMENT_CODE_ENTRANCE, offset=(5, 5)):
                return True
            if self.appear(EQUIPMENT_FULL, offset=(30, 30)):
                return False
            if self.handle_popup_confirm("EQUIPMENT_CODE"):
                continue
            if self.appear_then_click(EQUIPMENT_CODE_CONFIRM, offset=(5, 5), interval=3):
                continue
        else:
            return False

    def _code_apply(self, code=None):
        """执行清空、输入和确认应用装备码的完整流程。

        Args:
            code (str, optional): 待应用的装备码，None 表示仅清空。

        Returns:
            bool: 成功应用返回 True，否则返回 False。
        """
        for _ in range(5):
            if not self._code_preview_clear():
                continue
            if code is not None and code != EMPTY_CODE:
                success = self._code_input(code)
                if not success:
                    continue
            success = self._code_confirm()
            if success:
                logger.info("装备码应用完成")
                return True
            else:
                self.handle_storage_full()
        else:
            return False

    @staticmethod
    def _is_equipment_code(code):
        """校验字符串是否为合法的 Base64 装备码格式。

        Args:
            code (str): 待校验文本。

        Returns:
            bool: 格式合法返回 True，否则返回 False。
        """
        if not isinstance(code, str):
            return False
        code = code.strip().strip('\'"')
        if len(code) < len(EMPTY_CODE):
            return False
        if len(code) % 4 != 0:
            return False
        if not EQUIPMENT_CODE_PATTERN.fullmatch(code):
            return False
        if '=' in code.rstrip('='):
            return False
        return True

    @staticmethod
    def _code_from_text(text):
        """从包含多行或杂乱信息的文本中提取出有效装备码。

        Args:
            text (str): 待解析文本。

        Returns:
            str | None: 提取出的装备码，未提取到返回 None。
        """
        for line in reversed(str(text).splitlines()):
            line = line.strip().strip('\'"')
            if not line:
                continue

            lowered = line.lower()
            if any(keyword in lowered for keyword in [
                'not found',
                'unknown command',
                'no shell command implementation',
                'no primary clip',
                'exception',
                'error:',
                'security exception',
            ]):
                continue

            for prefix in ['text:', 'clipboard text:']:
                if lowered.startswith(prefix):
                    line = line[len(prefix):].strip().strip('\'"')
                    break

            if line.startswith('ClipData') and ':' in line:
                line = line.rsplit(':', 1)[1].strip().strip('\'"')

            if EquipmentCodeHandler._is_equipment_code(line):
                return line

            for match in EQUIPMENT_CODE_PATTERN.finditer(line):
                code = match.group(0).strip('=')
                padding = '=' * (-len(code) % 4)
                code = code + padding
                if EquipmentCodeHandler._is_equipment_code(code):
                    return code

        return None

    @staticmethod
    def _parcel_bytes(output):
        """从 Android service call 输出的十六进制转储中提取二进制字节流。

        Args:
            output (str): 命令输出的 Hex 文本。

        Returns:
            bytes: 解析出的二进制数据。
        """
        data = bytearray()
        for raw in str(output).splitlines():
            line = raw.strip()
            if line.startswith('0x') and ':' in line:
                line = line.split(':', 1)[1]
            elif 'Parcel(' in line:
                line = line.split('Parcel(', 1)[1]
            else:
                continue
            line = line.split("'", 1)[0]
            for word in re.findall(r'\b[0-9a-fA-F]{8}\b', line):
                data.extend(int(word, 16).to_bytes(4, 'little'))
        return bytes(data)

    @staticmethod
    def _code_from_parcel_output(output):
        """从 Parcel 序列化输出中提取装备码。

        Args:
            output (str): service call 输出。

        Returns:
            str | None: 装备码字符串，若未提取到返回 None。
        """
        data = EquipmentCodeHandler._parcel_bytes(output)
        if not data:
            return None

        for text in [
            data.decode('utf-8', errors='ignore'),
            data.decode('utf-16le', errors='ignore'),
        ]:
            code = EquipmentCodeHandler._code_from_text(text.replace('\x00', '\n'))
            if code is not None:
                return code

        return None

    @staticmethod
    def _code_from_clipboard_output(output):
        """从剪贴板命令输出中提取有效装备码。

        Args:
            output (str | bytes): 剪贴板输出数据。

        Returns:
            str | None: 装备码，未提取到返回 None。
        """
        if output is None:
            return None
        if isinstance(output, bytes):
            output = output.decode('utf-8', errors='ignore')

        code = EquipmentCodeHandler._code_from_parcel_output(output)
        if code is not None:
            return code

        return EquipmentCodeHandler._code_from_text(output)

    def _clipboard_adb(self):
        """通过 ADB Shell 读取系统剪贴板中的装备码。

        Returns:
            str | None: 读取到的装备码字符串，失败返回 None。
        """
        for command in [
            ['cmd', 'clipboard', 'get'],
            ['cmd', 'clipboard', 'get-primary-clip'],
            ['service', 'call', 'clipboard', '4', 's16', 'com.android.shell', 's16', '', 'i32', '0', 'i32', '0'],
        ]:
            try:
                output = self.device.adb_shell(command, timeout=3)
            except (EmulatorNotRunningError, RequestHumanTakeover):
                raise
            except Exception as e:
                logger.debug(f"通过 ADB 读取剪贴板失败: {e}")
                continue

            code = self._code_from_clipboard_output(output)
            if code is not None:
                logger.info("通过 ADB 读取装备码剪贴板成功")
                return code

        return None

    def _code_copy(self):
        """点击导出并用新出现的信息栏确认本次复制。"""
        copied = False
        for _ in self.loop(timeout=10, skip_first=False):
            # 上次复制留下的提示必须消失，才能识别本次点击后的提示。
            if self.info_bar_count():
                if copied:
                    return True
                continue
            if self.appear_then_click(EQUIPMENT_CODE_EXPORT, offset=(5, 5), interval=3):
                copied = True
        logger.warning('未确认装备码导出成功')
        return False

    def _code_export(self):
        """在装备码界面点击导出并将装备码复制到系统剪贴板读取。

        Returns:
            str | None: 导出的装备码字符串，导出失败返回 None。
        """
        if not self._code_copy():
            return None
        code = self._clipboard_adb()
        if code is not None:
            return code

        # 先准备备用后端，再复制新内容，避免初始化占用剪贴板的读取窗口。
        self.device.ensure_clipboard_uiautomator2()
        if not self._code_copy():
            return None
        try:
            code = self._code_from_clipboard_output(self.device.get_clipboard_uiautomator2())
        finally:
            # 备用后端可能临时切换前台，恢复游戏后重新记录画面。
            self.device.stuck_record_clear()
        if code is None:
            logger.warning('读取装备码剪贴板失败')
        return code

    def code_clear(self, name=None):
        """通过装备码功能清空当前舰船的所有装备，若配置开启则自动备份原装备码。

        Args:
            name (str, optional): 舰船名称或类型标识。

        Returns:
            bool: 清空成功返回 True，否则返回 False。
        """
        # 每次卸装独立交接，禁止复用上一艘舰船或上一轮失败留下的缓存。
        self.last_code = None
        if not self.equipment_code_supported():
            return False

        self._code_enter()
        if name is None:
            name = self.current_ship()
        code = None
        if self.equipment_code_export_to_config:
            code = self.get_code(name=name)
            if code is None:
                code = self._code_export()
                if not self._is_equipment_code(code):
                    logger.warning("装备码导出失败，跳过清空装备")
                    return False
                if not self.set_code(name=name, code=code):
                    logger.warning('装备码保存失败，保留当前装备')
                    return False
        if not self._code_apply(code=None):
            return False
        self.last_code = code
        return True

    def code_apply(self, name=None):
        """为当前舰船应用指定名称或暂存的装备码方案。

        Args:
            name (str, optional): 舰船名称或类型标识。

        Returns:
            bool: 应用成功返回 True，否则返回 False。
        """
        if not self.equipment_code_supported():
            return False

        self._code_enter()
        if name is None:
            name = self.current_ship()
        code = self.get_code(name=name)
        if code is None:
            code = self.last_code
        if not self._is_equipment_code(code):
            logger.warning("没有可用装备码，跳过装备应用")
            return False
        success = self._code_apply(code=code)
        if success:
            self.last_code = None
        return success
