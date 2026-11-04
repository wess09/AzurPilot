"""智能换船的可选装备交接，复用紧急委托的装备码状态流程。"""

from module.equipment.assets import (EQUIPMENT_CODE_ENTRANCE, EQUIPMENT_CODE_PAGE_CHECK,
                                     FLEET_DETAIL_CHECK)
from module.exception import FleetManagementError
from module.logger import logger
from module.campaign.fleet_training_notify import notify_failure
from module.retire.fleet_detail import FleetShipDetail
from module.runtime.fleet_equipment import EQUIPMENT_PATH, SHIP_TYPES, parse_codes, recognize_ship_type


class FleetRotationEquipment(FleetShipDetail):
    """只处理本轮目标舰位，待完成记录独立于换船失败记录保存。"""

    @notify_failure('装备更换失败', '换装准备未完成，尚未完成本轮装备交接。')
    def __init__(self, manager):
        super().__init__(manager)
        try:
            self.codes = parse_codes(self.config.cross_get(EQUIPMENT_PATH + '.Codes', '{}'))
        except ValueError as exc:
            raise FleetManagementError(str(exc)) from exc
        if self.config.SERVER != 'cn':
            raise FleetManagementError('自动换装备暂仅支持国服舰种模板')
        if not self.equipment_code_supported():
            raise FleetManagementError('当前控制方式不支持装备码自动输入')

    @notify_failure('装备更换失败', '未能退出上次中断的装备页面，保留原有恢复处理。')
    def recover_page(self):
        """中断停在已知装备页时先返回母港，交给原有完整舰队扫描。

        Pages:
            in: 装备码页、角色详情或其他原有可导航页面
            out: 已知装备页返回母港；其他页面不操作
        """
        if not self.device.has_cached_image:
            self.device.screenshot()
        if self.appear(EQUIPMENT_CODE_PAGE_CHECK):
            self._code_exit()
        if self.appear(EQUIPMENT_CODE_ENTRANCE):
            self._back_to_details()
        if self.appear(FLEET_DETAIL_CHECK):
            self._back_to_formation()
            self.manager._commit_formation()

    @notify_failure('装备更换失败', '换出舰船卸装未完成；保留待完成换装记录。')
    def clear_outgoing(self, fleet, slots):
        """先记下所有待恢复舰位，再依次清空全部换出舰船，最后才交给换船。

        Pages:
            in: prepare_rotation完成的选船页
            out: 原目标舰队编队页
        """
        pending = dict(self.config.cross_get(EQUIPMENT_PATH + '.State', {}))
        pending.update({f'{fleet}:{slot}': {'fleet': fleet, 'slot': slot} for slot in slots})
        self.config.cross_set(EQUIPMENT_PATH + '.State', pending)
        self._details(fleet)
        for slot in slots:
            if self._ship(slot):
                logger.attr('换出舰船卸装', f'{fleet}-{slot}')
                self._code_enter()
                if not self._code_apply(code=None):
                    raise FleetManagementError('换出舰船卸装失败，保留待完成换装记录')
                self._back_to_details()
        self._back_to_formation()

    @notify_failure('装备更换失败', '换入舰船装备恢复未完成；保留尚未完成的舰位记录。')
    def apply_pending(self):
        """按当前舰位实际舰种补完换装，失败不清记录，成功舰位逐一移除。

        Pages:
            in: Any；换船完成或中断后重扫
            out: 最后处理舰队的编队页
        """
        pending = dict(self.config.cross_get(EQUIPMENT_PATH + '.State', {}))
        for fleet in sorted({job['fleet'] for job in pending.values()}):
            self._details(fleet)
            slots = {slot for job in pending.values() if job['fleet'] == fleet
                     for slot in range((job['slot'] - 1) // 3 * 3 + 1, job['slot'] + 1)}
            occurrences = {}
            # 未换船的同舰种也占用一套；恢复时重新计入已完成舰位，不能从第一套重来。
            for slot in sorted(slots):
                key = f'{fleet}:{slot}'
                job = pending.get(key)
                if self._ship(slot):
                    kind, previous = None, None
                    for _ in self.loop(skip_first=False, timeout=10):
                        if self.appear(EQUIPMENT_CODE_ENTRANCE):
                            candidate = recognize_ship_type(self.device.image)
                            if candidate and candidate == previous:
                                kind = candidate
                                break
                            previous = candidate
                    if not kind:
                        raise FleetManagementError('未能唯一识别角色详情舰种，保留待完成换装记录')
                    group = (slot <= 3, kind)
                    index = occurrences.get(group, 0)
                    occurrences[group] = index + 1
                    code = self.codes.get(kind, ['', '', ''])[index]
                    if job is not None:
                        job = dict(job, kind=kind, code_index=index)
                        pending[key] = job
                        self.config.cross_set(EQUIPMENT_PATH + '.State', pending)
                    if job is not None and code:
                        logger.attr('换入舰船装备方案', f'{fleet}-{slot} {SHIP_TYPES[kind]} 第{index + 1}套')
                        self._code_enter()
                        if not self._code_apply(code=None):
                            raise FleetManagementError('换入舰船清空装备失败，保留待完成换装记录')
                        self._code_enter()
                        if not self._code_apply(code=code):
                            raise FleetManagementError('换入舰船装备码应用失败，保留待完成换装记录')
                    elif job is not None:
                        logger.info(f'{SHIP_TYPES[kind]}第{index + 1}套未填写装备码，保留换入舰船当前装备并继续')
                    self._back_to_details()
                if job is not None:
                    pending.pop(key)
                    self.config.cross_set(EQUIPMENT_PATH + '.State', pending)
            self._back_to_formation()
