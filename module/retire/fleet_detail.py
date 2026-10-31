"""舰队详情的固定舰位导航，供装备与培养读取共用。"""

from contextlib import contextmanager

from module.equipment.assets import EQUIPMENT_CODE_ENTRANCE, FLEET_DETAIL, FLEET_DETAIL_CHECK
from module.equipment.equipment import Equipment
from module.exception import FleetManagementError
from module.retire.fleet_management import position_button
from module.runtime.fleet_formation import DETAIL_LEFTS, bottom_fleet_index, detail_occupied, fleet_type_selected, selector_closed
from module.ui.assets import BACK_ARROW


class FleetShipDetail(Equipment):
    def __init__(self, manager):
        super().__init__(config=manager.config, device=manager.device)
        self.manager = manager

    @contextmanager
    def reuse_details(self):
        """同批候补读取保留详情页，离开本批次时统一返回编队。"""
        previous = self.__dict__.get('_reuse_details', False)
        self._reuse_details = True
        try:
            yield
        finally:
            self._reuse_details = previous
            if not previous and self.appear(FLEET_DETAIL_CHECK):
                self._back_to_formation()

    def _details(self, fleet):
        """确认目标队后进入详情。

        Pages:
            in: Any
            out: 指定水面舰队详情
        """
        if self.appear(FLEET_DETAIL_CHECK):
            if (fleet_type_selected(self.device.image, 'surface')
                    and bottom_fleet_index(self.device.image) == fleet and selector_closed(self.device.image)):
                self._equipment_fleet = fleet
                return
            self._back_to_formation()
        self.manager.finish_rotation()
        if not (self.manager._formation_visible() and fleet_type_selected(self.device.image, 'surface')
                and bottom_fleet_index(self.device.image) == fleet and selector_closed(self.device.image)):
            self.manager.fleet_enter(fleet)
        self.ui_click(FLEET_DETAIL, appear_button=self.manager._formation_visible,
                      check_button=FLEET_DETAIL_CHECK, retry_wait=2)
        self._equipment_fleet = fleet

    def _ship(self, slot):
        """按已确认的固定舰位进入角色详情，空位不点击。

        Pages:
            in: 舰队详情
            out: 角色详情；空位保持原页面
        """
        category = 'main' if slot <= 3 else 'vanguard'
        records = self.config.cross_get(self.manager.RESULT_PATH, {}).get(category, {}).get(str(self._equipment_fleet), [])
        if not any(ship.get('slot') == slot and ship.get('occupied', True) for ship in records):
            return False
        for _ in self.loop(timeout=10):
            if self.appear(FLEET_DETAIL_CHECK) and detail_occupied(self.device.image, slot):
                break
        else:
            raise FleetManagementError(f'未确认详情舰位{slot}已加载，不操作角色')
        left = DETAIL_LEFTS[slot - 1]
        button = position_button((left + 30, 220, left + 125, 400), f'详情舰位{slot}')
        self.ui_click(button, appear_button=FLEET_DETAIL_CHECK, check_button=EQUIPMENT_CODE_ENTRANCE, retry_wait=2)
        return True

    def _back_to_details(self):
        self.ui_back(check_button=FLEET_DETAIL_CHECK)

    def _back_to_formation(self):
        self.ui_click(BACK_ARROW, appear_button=FLEET_DETAIL_CHECK,
                      check_button=self.manager._formation_visible, retry_wait=2)
