"""候补舰队耗尽后，从常用中选择未编队的舰船，不更改常用标记。"""

from collections import Counter
from copy import deepcopy

from module.equipment.assets import EQUIPMENT_CODE_ENTRANCE
from module.exception import FleetManagementError
from module.ocr.ocr import Ocr
from module.os.ship_exp import ShipLevel
from module.awaken.assets import OCR_SHIP_LEVEL, OCR_SHIP_EXP
from module.retire.assets import DOCK_CHECK
from module.retire.fleet_management import position_button
from module.retire.fleet_training import FleetTrainingReader, TrainingExp, training_level
from module.retire.scanner import StatusScanner
from module.runtime.fleet_formation import FormationDockScanner
from module.runtime.fleet_training import completed, excluded
from module.ui.page import page_dock, page_fleet


class FavouriteScanner(FormationDockScanner):
    def __init__(self):
        super().__init__(fleets={0})
        self.status = StatusScanner()
        self.status_text = Ocr((0, 0, 138, 30), lang='ppocr_v6', name='常用舰船占用状态')

    def scan(self, image, **kwargs):
        cards = super().scan(image, **kwargs)
        for card in cards:
            if card.fleet != 0 or card.ship.get('review'):
                card.ship['busy'] = True
                continue
            pixels = image[card.y:card.y + 204, card.x:card.x + 138]
            # 大世界使用横向文字条，不带普通1至6队徽标，也必须排除。
            text = self.status_text.ocr([pixels[132:162]], direct_ocr=True)
            card.ship['busy'] = (self.status._match(pixels) != 'free'
                                 or any(word in str(text) for word in ('作战', '委托', '编队', '训练', '演习')))
        return cards


class FavouriteShips(FleetTrainingReader):
    def __init__(self, manager):
        if manager.config.SERVER != 'cn':
            raise FleetManagementError('常用候补当前仅支持国服1280×720布局')
        super().__init__(manager)

    def _pages(self, *, normal_dock=False):
        return self.manager._dock_pages(FavouriteScanner(), max_rows=float('inf'), normal_dock=normal_dock)

    def _scan(self, *, normal_dock=False):
        merged = []
        for _, merged in self._pages(normal_dock=normal_dock):
            pass
        return [dict(card.ship, fleet=card.fleet) for card, _ in merged]

    def _locate(self, name, *, normal_dock=False):
        for cards, _ in self._pages(normal_dock=normal_dock):
            matches = [card for card in cards if card.fleet == 0 and card.ship.get('name') == name
                       and not card.ship.get('busy') and not card.ship.get('review')]
            if len(matches) > 1:
                raise FleetManagementError('常用候补存在同名舰船，无法唯一确认，不执行换船')
            if matches:
                card = matches[0]
                return position_button((card.x + 20, card.y + 40, card.x + 115, card.y + 145), '常用候补舰船')
        raise FleetManagementError('未能重新确认未编队常用候补，不执行换船')

    def _profile(self, ship, targets):
        values = {}
        if 'level' in targets:
            level_reader = ShipLevel(OCR_SHIP_LEVEL, name='常用培养等级')
            exp_reader = TrainingExp(OCR_SHIP_EXP, name='常用培养经验')
            previous = None
            for _ in self.loop(skip_first=False, timeout=8):
                if self.appear(EQUIPMENT_CODE_ENTRANCE):
                    level = level_reader.ocr(self.device.image)
                    exp = exp_reader.ocr(self.device.image) if level > 0 else None
                    if level == ship['level'] and (level, exp) == previous:
                        values.update(level=training_level(level, exp), display_level=level, exp=exp)
                        break
                    previous = level, exp
            if 'level' not in values:
                raise FleetManagementError('常用候补等级未能从两张新截图确认，不执行换船')
        if 'affinity' in targets:
            values['affinity'] = self._affinity()
        return values

    def find(self, fleet, slot, targets, records, *, needed=0, reserved=(), observe=None):
        """只在常用内选择，前后排沿用目标舰位限制；培养数据在普通船坞详情实读。

        Pages:
            in: 编队或舰队详情
            out: 编队页
        """
        normal = bool(targets)
        self.manager.finish_rotation()
        self.manager.fleet_enter(fleet)
        if normal:
            # 选船页点击只会选中舰船，不能长按猜测进入详情；普通船坞单击才进入详情。
            self.manager._commit_formation()
            self.manager.ui_ensure(page_dock)
            self.manager._prepare_dock()
            self.manager.dock_filter_set(index='main' if slot <= 3 else 'vanguard', reset_index=True)
        else:
            self.manager.prepare_rotation(fleet, slots=[slot], scan=False)
        self.manager.dock_favourite_set(True)
        try:
            entries = self._scan(normal_dock=normal)
            counts = Counter(ship.get('name') for ship in entries)
            formation = self.config.cross_get(self.manager.RESULT_PATH, {})
            assigned = {ship.get('name') for teams in formation.values() if isinstance(teams, dict)
                        for ships in teams.values() for ship in ships if ship.get('occupied', True)}
            for ship in entries:
                name = ship.get('name')
                if (not name or ship.get('review') or ship.get('busy') or ship['fleet'] != 0
                        or counts[name] != 1 or name in assigned or name in reserved
                        or excluded(records.get(name, {}), targets)
                        or type(ship.get('emotion')) is not int or ship['emotion'] < needed):
                    continue
                if targets:
                    button = self._locate(name, normal_dock=True)
                    self.ui_click(button, appear_button=DOCK_CHECK, check_button=EQUIPMENT_CODE_ENTRANCE, retry_wait=2)
                    values = self._profile(ship, targets)
                    self.ui_back(DOCK_CHECK)
                    if observe is not None:
                        observe(name, values, ship.get('emotion'))
                    if completed(values, targets):
                        continue
                    ship.update(values)
                return ship
            return None
        finally:
            if self.manager.appear(DOCK_CHECK):
                self.manager.dock_favourite_set(False)
            self.manager._level_prepared = False
            if normal and self.manager.appear(DOCK_CHECK):
                self.manager.dock_reset()
                self.manager.ui_ensure(page_fleet)
            elif not normal:
                self.manager.finish_rotation()

    def replace(self, fleet, slot, candidate):
        """确认当前仍未编队且身份唯一后选入；换后按固定舰位重读目标队。

        Pages:
            in: 编队页
            out: 目标队编队页
        """
        self.manager.finish_rotation()
        self.manager.prepare_rotation(fleet, slots=[slot], scan=False)
        self.manager.dock_favourite_set(True)
        entries = self._scan()
        matches = [ship for ship in entries if ship.get('name') == candidate['name']]
        if (len(matches) != 1 or matches[0]['fleet'] != 0 or matches[0].get('busy')
                or matches[0].get('review')):
            raise FleetManagementError('常用候补身份或空闲状态已变化，保留待确认记录')
        button = self._locate(candidate['name'])
        baseline = self.device.image.copy()
        self.device.click(button)
        self.manager._confirm_replacement(baseline)
        self.manager._rotation_picker = None
        self.manager._level_prepared = False
        # 移除旧舰位卡面；从固定详情重新采集新船，不能把旧画像当作新船身份。
        self.manager.__dict__.get('_slot_portraits', {}).pop((fleet, slot), None)
        result = deepcopy(self.config.cross_get(self.manager.RESULT_PATH, {}))
        category = 'main' if slot <= 3 else 'vanguard'
        result[category][str(fleet)] = [dict(candidate, slot=slot) if ship.get('slot') == slot else ship
                                      for ship in result[category][str(fleet)]]
        self.manager._save_result(result)
        FleetTrainingReader(self.manager).inventory([fleet], slots={fleet: [slot]})
        return self.manager.rotation_readings()
