"""装备码（配装码）解析与应用模块。
支持从游戏内读取 Base64 编码的装备方案码，
并通过 UI 自动化将方案中指定的装备应用到舰船上。"""

import re

import cv2
import numpy as np
import yaml

from module.base.timer import Timer
from module.device.method.utils import HierarchyButton
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
    last_code: str = None
    FASTINPUT_IME = 'com.github.uiautomator/.FastInputIME'

    @property
    def equipment_code_config_key(self):
        return None

    @property
    def equipment_code_export_to_config(self):
        if self.equipment_code_config_key:
            return True
        return getattr(self.config, 'EquipmentCode_ExportToConfig', False)

    def _code_config_load(self):
        key = self.equipment_code_config_key
        if key:
            raw = self.config.cross_get(keys=key)
        else:
            raw = getattr(self.config, 'EquipmentCode_Config', '')

        config = {}
        try:
            for item in yaml.safe_load_all(raw or ''):
                if item:
                    config.update(item)
        except Exception:
            logger.error("加载装备码配置失败")
        return config

    def _code_config_save(self, config):
        value = yaml.safe_dump(config)
        key = self.equipment_code_config_key
        if key:
            self.config.cross_set(keys=key, value=value)
        elif hasattr(self.config, 'EquipmentCode_Config'):
            self.config.EquipmentCode_Config = value
        else:
            logger.warning("无装备码配置目标，跳过保存")

    def equipment_code_supported(self):
        method = self.config.Emulator_ControlMethod
        if method in U2_CONTROL_METHODS:
            return True

        logger.warning(
            f"Equipment code requires uiautomator2 based control method, "
            f"current control method is {method}, skip equipment change"
        )
        return False

    def get_code(self, name):
        config = self._code_config_load()
        code = config.get(name)
        if code is None:
            logger.error(f"[装备-代码] 配置不包含 {name} 的装备代码")
        return code

    def set_code(self, name, code):
        config = self._code_config_load()
        try:
            config.update({name: code})
            self._code_config_save(config)
        except Exception:
            logger.error("设置装备码配置失败")

    def current_ship(self):
        """
        Currently, only supports common CV recognization

        Pages:
            in: equipment_code
        """
        for _ in self.loop():
            if not self.appear(EMPTY_SHIP_R):
                break
        if TEMPLATE_BOGUE.match(self.device.image, scaling=1.46):  # image has rotation
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
        """
        Pages:
            in: ship_detail
            out: equipment_code
        """
        for _ in self.loop():
            if self.appear(EQUIPMENT_CODE_PAGE_CHECK, offset=(5, 5)):
                break

            if self.appear_then_click(EQUIPMENT_CODE_ENTRANCE, offset=(5, 5), interval=1):
                continue

    def _code_exit(self):
        """
        Pages:
            in: equipment_code
            out: ship_detail
        """
        self.ui_back(check_button=EQUIPMENT_CODE_ENTRANCE)

    def is_code_preview_empty(self):
        # 只有所有可用槽位都正向命中空槽，才能确认预览已清空。
        return all(
            self.appear(button, offset=(5, 5))
            for button in EQUIPMENT_PREVIEW_EMPTY[:5]
        ) and (
            self.appear(EQUIPMENT_CODE_EQUIP_5_LOCKED, offset=(5, 5))
            or self.appear(EQUIPMENT_CODE_EQUIP_5, offset=(5, 5))
        )

    def _code_preview_slot_occupied(self, button):
        return button.match_luma(self.device.image, offset=(2, 2), similarity=0.85)

    def _code_special_equip_occupied(self):
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
        for _ in self.loop(timeout=2):
            if self.is_code_preview_empty():
                return True

            if self.appear_then_click(EQUIPMENT_CODE_CLEAR, offset=(5, 5), interval=1):
                continue
        else:
            return False

    def fastinput_ime_enable(self):
        self.device.adb_shell(['am', 'start', '-a', 'android.settings.INPUT_METHOD_SETTINGS'])
        timeout = Timer(10).start()
        while 1:
            if timeout.reached():
                logger.warning("启用FastInputIME超时")
                break

            h = self.device.dump_hierarchy_adb()

            def appear(xpath):
                return bool(HierarchyButton(h, xpath))

            def appear_then_click(xpath):
                b = HierarchyButton(h, xpath)
                if b:
                    self.device.click(b)
                    return True
                else:
                    return False

            if appear_then_click('//*[@resource-id="android:id/title" and @text="FastInputIME"]/following-sibling::*[@resource-id="android:id/switch_widget" and @checked="false"]'):
                continue
            if appear_then_click('//*[@resource-id="android:id/button1"]'):
                continue
            # Disable one other enabled IME at a time
            if appear_then_click('(//*[@resource-id="android:id/title" and @text!="FastInputIME"]/following-sibling::*[@resource-id="android:id/switch_widget" and @enabled="true" and @checked="true"])[1]'):
                continue
            if appear('//*[@resource-id="android:id/title" and @text="FastInputIME"]/following-sibling::*[@resource-id="android:id/switch_widget" and @checked="true"]') \
                    and not appear('//*[@resource-id="android:id/title" and @text!="FastInputIME"]/following-sibling::*[@resource-id="android:id/switch_widget" and @enabled="true" and @checked="true"]'):
                break

        self.device.adb_shell(['input', 'keyevent', '4'])

    def set_fastinput_ime(self):
        d = self.device.u2
        try:
            name, _ = d.current_ime()
        except Exception:
            name = None
        if name == self.FASTINPUT_IME:
            return
        try:
            d.set_fastinput_ime(True)
        except Exception:
            logger.warning("[装备-代码] FastInputIME未启用，尝试启用")
            self.fastinput_ime_enable()

    @staticmethod
    def _adb_input_text_escape(text):
        text = str(text).replace('%', '%s')
        for char in ['\\', '"', "'", '`', '$', '&', '|', '<', '>', ';', '(', ')', '*']:
            text = text.replace(char, f'\\{char}')
        return text

    def _code_input_adb(self, code):
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

    def _code_input_uiautomator2(self, code):
        try:
            d = self.device.u2
            d.send_keys(text=code, clear=True)
            d.send_action(code="done")
            logger.info("通过 uiautomator2 输入装备码")
            return True
        except Exception as e:
            logger.warning(f"通过 uiautomator2 输入装备码失败: {e}")
            return False

    def _code_wait_preview_loaded(self):
        """等待装备码预览加载完成。"""
        for _ in self.loop(timeout=10, skip_first=False):
            # End：正向退出判断必须位于点击操作之前。
            if self.is_code_preview_loaded():
                return True

            if self.appear_then_click(EQUIPMENT_CODE_ENTER, offset=(5, 5), interval=3):
                continue

        return False

    def _code_input(self, code):
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

        if self._code_input_uiautomator2(code):
            if self._code_wait_preview_loaded():
                return True

        logger.warning("装备码加载失败")
        return False

    def _code_confirm(self):
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
        for _ in range(5):
            self._code_preview_clear()
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
        if output is None:
            return None
        if isinstance(output, bytes):
            output = output.decode('utf-8', errors='ignore')

        code = EquipmentCodeHandler._code_from_parcel_output(output)
        if code is not None:
            return code

        return EquipmentCodeHandler._code_from_text(output)

    def _clipboard_adb(self):
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

    def _clipboard_uiautomator2(self):
        try:
            output = self.device.clipboard
        except (EmulatorNotRunningError, RequestHumanTakeover):
            raise
        except Exception as e:
            logger.warning(f"通过 uiautomator2 读取剪贴板失败: {e}")
            return None

        code = self._code_from_clipboard_output(output)
        if code is not None:
            logger.info("通过 uiautomator2 读取装备码剪贴板成功")
        return code

    def _clipboard_get(self):
        code = self._clipboard_adb()
        if code is not None:
            return code

        code = self._clipboard_uiautomator2()
        if code is not None:
            return code

        logger.warning("读取装备码剪贴板失败")
        return None

    def _code_export(self):
        self.handle_info_bar()
        self.set_fastinput_ime()
        for _ in self.loop(timeout=10):
            if self.info_bar_count():
                break
            if self.appear_then_click(EQUIPMENT_CODE_EXPORT, offset=(5, 5), interval=3):
                continue
        return self._clipboard_get()

    def code_clear(self, name=None):
        if not self.equipment_code_supported():
            return False

        self._code_enter()
        if name is None:
            name = self.current_ship()
        if self.equipment_code_export_to_config and self.get_code(name=name) is None:
            self.last_code = self._code_export()
            if self.last_code is None:
                logger.warning("装备码导出失败，跳过清空装备")
                return False
            self.set_code(name=name, code=self.last_code)
        return self._code_apply(code=None)

    def code_apply(self, name=None):
        if not self.equipment_code_supported():
            return False

        self._code_enter()
        if name is None:
            name = self.current_ship()
        code = self.get_code(name=name)
        if code is None:
            code = self.last_code
        if code is None:
            logger.warning("没有可用装备码，跳过装备应用")
            return False
        return self._code_apply(code=code)
