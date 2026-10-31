"""培养舰船等级、经验与好感实读，固定坐标基于1280×720国服截图。"""

from copy import deepcopy
from bisect import bisect_right
import re
import unicodedata

import cv2

from module.equipment.assets import EQUIPMENT_CODE_ENTRANCE, FLEET_DETAIL_CHECK
from module.base.timer import Timer
from module.exception import FleetManagementError
from module.ocr.ocr import Ocr
from module.os.ship_exp import ShipLevel, ShipExp
from module.os.ship_exp_data import LIST_SHIP_EXP
from module.awaken.assets import OCR_SHIP_LEVEL, OCR_SHIP_EXP
from module.retire.fleet_detail import FleetShipDetail
from module.retire.fleet_management import position_button
from module.runtime.fleet_formation import FormationDetailScanner, CATEGORY_SLOTS
from module.ui.assets import BACK_ARROW
from module.logger import logger


def training_level(level, exp):
    """复用大世界累计经验口径，计入未突破时存储的经验，不执行突破。"""
    if type(level) is not int or not 1 <= level <= len(LIST_SHIP_EXP):
        return None
    if type(exp) is not int or exp < 0:
        return level
    return bisect_right(LIST_SHIP_EXP, LIST_SHIP_EXP[level - 1] + exp)


def parse_affinity(text):
    text = re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(text)))
    # 部分誓约书的条件行会带入相邻状态字，只读取完整的当前值字段；多个字段不能猜测。
    matches = re.findall(r'好感度达到100\(当前(\d{1,3})\)', text)
    if len(matches) == 1 and 0 <= int(matches[0]) <= 200:
        return int(matches[0])
    return None


class AffinityText(Ocr):
    def pre_process(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        return cv2.resize(255 - gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)


class TrainingExp(ShipExp):
    """沿用经验识别与文本修正，解析失败保留未知，避免展示成实际的零经验。"""

    def ocr(self, image, direct_ocr=False):
        text = Ocr.ocr(self, image, direct_ocr=direct_ocr)
        if isinstance(text, list):
            text = text[0] if text else ''
        match = re.search(r'(\d+)/', str(text))
        return int(match[1]) if match else None


class AffinityReader:
    def __init__(self):
        # 未达成时数字是金色，已达成时为白色；两条通道均须解析“当前”后的数值。
        area = (892, 527, 1148, 551)
        self.white = AffinityText(area, lang='ppocr_v6', name='培养好感白字')
        self.gold = Ocr(area, lang='ppocr_v6', letter=(150, 135, 90), threshold=96, name='培养好感金字')

    def read(self, image):
        values = {value for reader in (self.white, self.gold)
                  if (value := parse_affinity(reader.ocr(image))) is not None}
        return values.pop() if len(values) == 1 else None


class FleetTrainingReader(FleetShipDetail):
    def recover_page(self):
        """仅在持久读取记录存在时，按正向页面状态退出中断的读取。

        Pages:
            in: 好感弹窗、角色详情、舰队详情或可导航原页面
            out: 已知读取页面返回编队；其他页面保留
        """
        if not self.device.has_cached_image:
            self.device.screenshot()
        if not self.appear(EQUIPMENT_CODE_ENTRANCE) and AffinityReader().read(self.device.image) is not None:
            self.ui_click(BACK_ARROW, appear_button=lambda: AffinityReader().read(self.device.image) is not None,
                          check_button=EQUIPMENT_CODE_ENTRANCE, retry_wait=2)
        reading = self.config.cross_get('FleetInfo.FleetTraining.State', {}).get('reading', {})
        if reading.get('favourite'):
            from module.retire.assets import DOCK_CHECK
            if self.appear(EQUIPMENT_CODE_ENTRANCE):
                self.ui_back(DOCK_CHECK)
            if self.appear(DOCK_CHECK):
                self.manager.dock_reset()
            return
        if self.appear(EQUIPMENT_CODE_ENTRANCE):
            self._back_to_details()
        if self.appear(FLEET_DETAIL_CHECK):
            self._back_to_formation()

    def inventory(self, fleets, *, slots=None):
        """按固定舰位定位，从勾选舰位进入选船页，只实读目标舰队。

        Pages:
            in: Any
            out: 最后一个舰队的编队页
        """
        fleets = sorted(fleets)
        result = deepcopy(self.config.cross_get(self.manager.RESULT_PATH, {}))
        scanner = FormationDetailScanner()
        for fleet in fleets:
            image, _, _ = self.manager._capture_formation(fleet)
            formation = scanner.scan(image)
            for category in ('main', 'vanguard'):
                previous = {ship.get('slot'): ship for ship in result.get(category, {}).get(str(fleet), [])}
                records = []
                for slot in CATEGORY_SLOTS[category]:
                    ship = formation[slot]
                    if not ship.get('occupied'):
                        continue
                    old = previous.get(slot, {})
                    if old.get('name') == ship.get('name'):
                        ship['emotion'] = old.get('emotion')
                    records.append(ship)
                result.setdefault(category, {})[str(fleet)] = records
        self.manager._save_result(result)
        for fleet in fleets:
            self.manager.prepare_rotation(fleet, slots=(slots or {}).get(fleet), fleets={fleet})
            self.manager.finish_rotation()
        return self.config.cross_get(self.manager.RESULT_PATH, {})

    def _affinity(self):
        reader = AffinityReader()
        previous = None
        click = position_button((583, 106, 649, 158), '打开好感详情')
        click_timer = Timer(2)
        for _ in self.loop(skip_first=False, timeout=12):
            value = reader.read(self.device.image)
            if value is not None and value == previous:
                break
            previous = value
            if self.appear(EQUIPMENT_CODE_ENTRANCE):
                if click_timer.reached():
                    self.device.click(click)
                    click_timer.reset()
        else:
            raise FleetManagementError('好感当前值未能从两张新截图确认，不记录培养完成')
        self.ui_click(BACK_ARROW, appear_button=lambda: reader.read(self.device.image) is not None,
                      check_button=EQUIPMENT_CODE_ENTRANCE, retry_wait=2)
        return value

    def read(self, fleet, slots, targets):
        """同次读取全部启用条件，等级复用大世界经验识别器。

        Pages:
            in: Any
            out: 指定舰队编队页
        """
        if self.config.SERVER != 'cn':
            raise FleetManagementError('等级/好感培养调度当前仅验证国服1280×720布局')
        self._details(fleet)
        readings = {}
        for slot in sorted(slots):
            if not self._ship(slot):
                continue
            values = {}
            if 'level' in targets:
                level_reader, exp_reader = ShipLevel(OCR_SHIP_LEVEL, name='培养等级'), TrainingExp(OCR_SHIP_EXP, name='培养经验')
                category = 'main' if slot <= 3 else 'vanguard'
                reference = next((ship.get('level', 0) for ship in self.config.cross_get(self.manager.RESULT_PATH, {})
                                  .get(category, {}).get(str(fleet), []) if ship.get('slot') == slot), 0)
                previous = None
                for _ in self.loop(skip_first=False, timeout=8):
                    if self.appear(EQUIPMENT_CODE_ENTRANCE):
                        value = level_reader.ocr(self.device.image)
                        exp = exp_reader.ocr(self.device.image) if value > 0 else None
                        if value > 0 and (value, exp) == previous and (not reference or value == reference):
                            values.update(level=training_level(value, exp), display_level=value, exp=exp)
                            logger.attr(f'第{fleet}舰队{slot}位界面等级/实际等级/经验',
                                        f'{value}/{values["level"]}/{exp}')
                            break
                        previous = (value, exp)
                if 'level' not in values:
                    raise FleetManagementError('培养等级未能从两张新截图确认，不记录培养完成')
            if 'affinity' in targets:
                values['affinity'] = self._affinity()
            readings[slot] = values
            self._back_to_details()
        if not self.__dict__.get('_reuse_details', False):
            self._back_to_formation()
        return readings
