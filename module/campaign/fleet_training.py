"""等级/好感培养联动既有同号舰位换船，不重新实现心情调度。"""

from copy import deepcopy
from datetime import datetime, timedelta

from module.config.time_source import now
from module.equipment.fleet_rotation import FleetRotationEquipment
from module.exception import FleetManagementError, ScriptEnd
from module.logger import logger
from module.campaign.fleet_training_notify import notify_training
from module.retire.fleet_management import FleetManagement
from module.retire.fleet_training import FleetTrainingReader
from module.runtime.fleet_equipment import EQUIPMENT_PATH
from module.runtime.fleet_rotation import (ROTATION_PATH, active_fleets, calibration_changes, parse_rules,
                                           rank_sources, recorded_morale, supported)
from module.runtime.fleet_training import (TRAINING_PATH, completed, due, excluded, goals, identity,
                                           interval, mark_checked, observe, restore_context, ships, state)


class TrainingSession:
    def __init__(self, runner, manager, context, rules, selected):
        self.runner, self.manager, self.context = runner, manager, context
        self.config = runner.campaign.config
        self.rules, self.selected = rules, selected
        self.targets = goals(self.config)
        self.saved = state(self.config)
        self.reader = FleetTrainingReader(manager)
        self.inventory_fleets = set(selected.values())
        self.equipment_used = False
        self.replaced_fleets = set()
        self.sources_refreshed = False
        self.checking_targets = False
        self.changes = []

    def favourite_job(self, fleet, slot, outgoing, *, needed=0, reserved=()):
        from module.retire.fleet_favourite import FavouriteShips
        self.saved['reading'] = dict(fleet=fleet, slots=[slot], favourite=True)
        self.save()

        def record(name, values, emotion):
            observe(self.saved, name, values, self.targets, emotion=emotion)
            self.save()

        candidate = FavouriteShips(self.manager).find(fleet, slot, self.targets, self.saved['records'],
                                                      needed=needed, reserved=reserved, observe=record)
        self.saved.pop('reading', None)
        self.save()
        if candidate is not None:
            return dict(fleet=fleet, slot=slot, source=0, outgoing=outgoing, incoming=candidate['name'],
                        targets=dict(self.targets), candidate=candidate)
        return None

    def rotation_rule(self, fleet):
        rule = self.rules[str(fleet)]
        if self.config.cross_get('FleetInfo.FleetTraining.StopOnComplete', False) is True:
            # 等待本轮其他舰船毕业时，不把已毕业舰位换成下一批。
            rule = dict(rule, slots=[slot for slot in rule['slots']
                        if not completed(self.saved['records'].get(
                            identity(ships(self.result, fleet).get(slot), self.result), {}), self.targets)])
        return rule

    def stop_when_complete(self):
        current = {}
        for fleet in self.selected.values():
            current[fleet] = self.inspect(fleet, self.rules[str(fleet)]['slots'], defer_completion=True)
        ready = [(fleet, slot, name) for fleet, names in current.items() for slot, name in names.items()
                 if completed(self.saved['records'][name], self.targets)]
        if ready:
            self.refresh_sources()
            for fleet, slot, name in ready:
                if identity(ships(self.result, fleet).get(slot), self.result) != name:
                    self.delay('全舰队扫描后毕业舰船身份无法唯一确认，不停止任务')
                self.saved['records'][name].update(completed_for=dict(self.targets),
                                                   completed_at=now().isoformat(timespec='seconds'))
            self.save()
        expected = {(fleet, slot) for fleet in self.selected.values() for slot in self.rules[str(fleet)]['slots']
                    if slot in ships(self.result, fleet)}
        mark_checked(self.config, self.context, self.targets)
        if expected and expected == {(fleet, slot) for fleet, slot, _ in ready}:
            self.manager.finish_rotation()
            self.manager._commit_formation()
            logger.info('本轮全部培养舰船已达到等级/好感目标，停止当前练级任务')
            self.config.Scheduler_Enable = False
            notify_training(self.config, self.rules, self.selected, status='培养完成，已停止练级')
            self.config.task_stop()
        return True

    @property
    def result(self):
        return self.config.cross_get(self.manager.RESULT_PATH, {})

    def save(self):
        # 心情扣减与扫描计时独立更新；培养会话不能用旧快照覆盖这些持久信息。
        latest = state(self.config)
        if 'checks' in latest:
            self.saved['checks'] = latest['checks']
        self.config.cross_set(TRAINING_PATH, deepcopy(self.saved))

    def delay(self, message):
        logger.warning(message)
        self.save()
        if self.checking_targets:
            mark_checked(self.config, self.context, self.targets)
        try:
            target = now() + timedelta(hours=max(1 / 60, interval(self.config)))
        except OverflowError:
            # 配置不限制小时数；超出日期表示范围时保留配置，等待到可表示的最晚时刻。
            target = datetime.max
        self.config.task_delay(target=target)
        raise ScriptEnd(message)

    def inspect(self, fleet, slots, *, defer_completion=False):
        self.saved['reading'] = dict(fleet=fleet, slots=list(slots))
        self.save()
        readings = self.reader.read(fleet, slots, self.targets)
        self.saved.pop('reading', None)
        known = {}
        for slot in slots:
            ship = ships(self.result, fleet).get(slot)
            if ship is None:
                continue
            name = identity(ship, self.result)
            reading = readings.get(slot, {})
            missing = ['等级' if metric == 'level' else '好感' for metric in self.targets
                       if type(reading.get(metric)) is not int]
            if missing:
                self.delay(f'第{fleet}舰队{slot}位培养数据未确认（{"、".join(missing)}），不记录完成')
            if name is None:
                name = identity(ship, self.result, allow_duplicates=True)
                if name is None:
                    self.delay(f'第{fleet}舰队{slot}位培养舰名未确认，不记录完成')
                # 舰位读数仅供展示，不能写入按舰名保存的完成/排除记录，也不参与中断互换。
                self.saved.setdefault('readings', {})[f'{fleet}:{slot}'] = {
                    'name': name, 'fleet': fleet, 'slot': slot, 'level': ship.get('level'),
                    'emotion': ship.get('emotion'), 'checked_at': now().isoformat(timespec='seconds'), **reading}
                logger.attr(f'第{fleet}舰队{slot}位{name}培养实读', reading)
                if completed(reading, self.targets):
                    self.delay(f'第{fleet}舰队{slot}位{name}存在同名舰船；已读到达标数据，但身份不唯一，不记录完成或换船')
                logger.info('同名舰船实读已按舰位保存，尚未全部达标，继续培养，不合并同名进度')
                continue
            was_completed = excluded(self.saved['records'].get(name, {}), self.targets)
            observe(self.saved, name, reading, self.targets, fleet=fleet, slot=slot, emotion=ship.get('emotion'))
            if defer_completion and not was_completed:
                self.saved['records'][name].pop('completed_for', None)
                self.saved['records'][name].pop('completed_at', None)
            known[slot] = name
        self.save()
        return known

    def recover(self):
        """中断前已落盘的互换必须按双方身份核实，不盲目重复。"""
        for key, job in list(self.saved['pending'].items()):
            target = identity(ships(self.result, job['fleet']).get(job['slot']), self.result)
            if job['source'] == 0:
                if target == job['incoming']:
                    del self.saved['pending'][key]
                elif target != job['outgoing']:
                    raise FleetManagementError('常用换船中断后的目标舰位身份未确认，保留记录')
                elif job.get('targets', self.targets) != self.targets:
                    del self.saved['pending'][key]
                continue
            source = identity(ships(self.result, job['source']).get(job['slot']), self.result)
            if (target, source) == (job['incoming'], job['outgoing']):
                del self.saved['pending'][key]
            elif ((target, source) == (job['outgoing'], job['incoming'])
                  and job.get('targets', self.targets) != self.targets):
                del self.saved['pending'][key]
            elif (target, source) != (job['outgoing'], job['incoming']):
                raise FleetManagementError('培养互换中断后的双方舰位未确认，保留记录，不能重复换船')
        self.save()

    def prepare(self, fleet):
        snapshots = self.manager.prepare_rotation(fleet, slots=self.rules[str(fleet)]['slots'], scan=False)
        measured = {number: values for number, values in snapshots.items() if number in self.inventory_fleets}
        self.config.cross_set_many(calibration_changes(self.config.data, measured, now()))
        self.runner.campaign.emotion.calibrate_selected(measured)
        return snapshots

    def refresh_sources(self):
        """确认需要换船后完整扫描一轮，同轮复用结果，不受额外间隔限制。"""
        if self.sources_refreshed:
            return
        self.sources_refreshed = True
        logger.info('已确认需要换船，完整扫描全舰队后再选择候补')
        self.manager.finish_rotation()
        self.manager.run(update_emotion=True)
        self.inventory_fleets.update(range(1, 7))
        snapshots = {fleet: recorded_morale(self.result, fleet) for fleet in range(1, 7)}
        self.config.cross_set_many(calibration_changes(self.config.data, snapshots, now()))
        self.runner.campaign.emotion.calibrate_selected(snapshots)

    def process(self, *, fresh=False, force=False):
        if not self.targets or not self.selected or (not force and not due(self.config, self.context) and not self.saved['pending']):
            return False
        self.checking_targets = True
        self.recover()
        if self.config.cross_get('FleetInfo.FleetTraining.StopOnComplete', False) is True:
            return self.stop_when_complete()
        for role, fleet in self.selected.items():
            rule = self.rules[str(fleet)]
            current = self.inspect(fleet, rule['slots'], defer_completion=True)
            ready = [slot for slot, name in current.items()
                     if completed(self.saved['records'][name], self.targets)
                     or excluded(self.saved['records'][name], self.targets)]
            if not ready:
                continue
            self.refresh_sources()
            invalid = [slot for slot in ready
                       if identity(ships(self.result, fleet).get(slot), self.result) != current[slot]]
            if invalid:
                self.delay('全舰队扫描后毕业舰船身份无法唯一确认，保留读数，不执行换船')
            # 首次局部读取不足以排除其他舰队的同名船；完整扫描确认后才持久标记毕业。
            for slot in ready:
                record = self.saved['records'][current[slot]]
                if not excluded(record, self.targets):
                    record.update(completed_for=dict(self.targets), completed_at=now().isoformat(timespec='seconds'))
            self.save()
            for source in rule['sources']:
                if source not in self.inventory_fleets:
                    self.reader.inventory([source])
                    self.inventory_fleets.add(source)
            snapshots = {source: recorded_morale(self.result, source) for source in rule['sources']}
            jobs = []
            with self.reader.reuse_details():
                for slot in ready:
                    key = f'{fleet}:{slot}'
                    job = self.saved['pending'].get(key)
                    if job is None:
                        order = rank_sources(dict(rule, slots=[slot]), snapshots,
                                             selected_only=self.runner.campaign.emotion.selected_only)
                        for source in order:
                            candidate = ships(self.result, source).get(slot)
                            name = identity(candidate, self.result)
                            if name is None or excluded(self.saved['records'].get(name, {}), self.targets):
                                continue
                            # 候补也实读，避免换入尚未登记但已达到全部目标的舰船。
                            names = self.inspect(source, [slot])
                            if slot not in names or excluded(self.saved['records'][name], self.targets):
                                continue
                            job = dict(fleet=fleet, slot=slot, source=source, outgoing=current[slot], incoming=name,
                                       targets=dict(self.targets))
                            break
                    if job is None and rule.get('favourite'):
                        job = self.favourite_job(fleet, slot, current[slot],
                                                 reserved=[job['incoming'] for _, job in jobs])
                    if job is None:
                        self.delay(f'第{fleet}舰队{slot}位已培养完成，但没有合适候补，延迟当前任务')
                    jobs.append((key, job))
            if not jobs:
                continue
            self.prepare(fleet)
            self.saved['pending'].update(jobs)
            self.save()
            equipment = None
            if self.config.cross_get(EQUIPMENT_PATH + '.Enabled', False) is True:
                equipment = FleetRotationEquipment(self.manager)
                equipment.clear_outgoing(fleet, [job['slot'] for _, job in jobs])
                self.equipment_used = True
            for key, job in jobs:
                if goals(self.config) != self.targets:
                    break
                if job['source'] == 0:
                    from module.retire.fleet_favourite import FavouriteShips
                    snapshots = FavouriteShips(self.manager).replace(fleet, job['slot'], job['candidate'])
                else:
                    snapshots = self.manager.rotate_slot(job['source'], job['slot'], fleet)
                self.config.cross_set_many(calibration_changes(self.config.data, snapshots, now()))
                self.runner.campaign.emotion.calibrate_selected(snapshots)
                actual = identity(ships(self.result, fleet).get(job['slot']), self.result)
                if actual != job['incoming']:
                    raise FleetManagementError('培养换船后的身份未确认，保留待确认记录')
                self.changes.append(job)
                del self.saved['pending'][key]
                self.save()
            self.manager.finish_rotation()
            self.replaced_fleets.add(fleet)
            if equipment is not None:
                equipment.apply_pending()
            if goals(self.config) == self.targets:
                # 候补刚实读且换后身份已确认，直接迁移读数位置，不再次逐船打开详情。
                for _, job in jobs:
                    incoming = self.saved['records'][job['incoming']]
                    ship = ships(self.result, fleet)[job['slot']]
                    incoming.update(fleet=fleet, slot=job['slot'], emotion=ship.get('emotion'))
                self.save()
        mark_checked(self.config, self.context, self.targets)
        return True

    def filter_sources(self, order, rule, fleet):
        """心情临时轮换也不能把已完成培养的舰船选回来。"""
        for source in order:
            if source not in self.inventory_fleets:
                self.reader.inventory([source])
                self.inventory_fleets.add(source)
            names = self.inspect(source, rule['slots'])
            if all(slot in names and not excluded(self.saved['records'][names[slot]], self.targets)
                   for slot in rule['slots']):
                self.manager.finish_rotation()
                self.manager.fleet_enter(fleet)
                return [source]
        self.manager.finish_rotation()
        self.manager.fleet_enter(fleet)
        return []


def rotate_favourite_fallback(runner, manager, context, rules, selected, fleet, rule, snapshots, needed,
                               states, training=None):
    """整队候补不可用时逐舰位核对，仍先用对应候补舰位，最后才使用常用。"""
    session = training or TrainingSession(runner, manager, context, rules, selected)
    config = runner.campaign.config
    jobs = []
    for slot in rule['slots']:
        order = rank_sources(dict(rule, slots=[slot]), snapshots, needed,
                             selected_only=runner.campaign.emotion.selected_only)
        if training is not None:
            order = training.filter_sources(order, dict(rule, slots=[slot]), fleet)
        outgoing = ships(session.result, fleet).get(slot, {}).get('name') or '未确认舰名'
        if order:
            source = order[0]
            incoming = ships(session.result, source).get(slot, {}).get('name') or '未确认舰名'
            jobs.append(dict(fleet=fleet, slot=slot, source=source, incoming=incoming, outgoing=outgoing))
        else:
            job = session.favourite_job(fleet, slot, outgoing, needed=needed,
                                       reserved=[item['incoming'] for item in jobs])
            if job:
                jobs.append(job)
    if not jobs:
        return []
    equipment = None
    if config.cross_get(EQUIPMENT_PATH + '.Enabled', False) is True:
        equipment = FleetRotationEquipment(manager)
        equipment.clear_outgoing(fleet, [job['slot'] for job in jobs])
        session.equipment_used = True
    changes = []
    for job in jobs:
        if config.cross_get(ROTATION_PATH + '.Enabled', False) is not True:
            break
        states[str(fleet)] = dict(source=job['source'], pending=dict(slot=job['slot']), rescan=True)
        config.cross_set(ROTATION_PATH + '.State', states)
        if job['source'] == 0:
            from module.retire.fleet_favourite import FavouriteShips
            values = FavouriteShips(manager).replace(fleet, job['slot'], job['candidate'])
            if identity(ships(session.result, fleet).get(job['slot']), session.result) != job['incoming']:
                raise FleetManagementError('常用换船后目标舰位身份未确认，下次重扫实际编队')
        else:
            manager.prepare_rotation(fleet, slots=[job['slot']], scan=False)
            values = manager.rotate_slot(job['source'], job['slot'], fleet)
        config.cross_set_many(calibration_changes(config.data, values, now()))
        runner.campaign.emotion.calibrate_selected(values)
        changes.append(job)
        states[str(fleet)] = dict(last_source=job['source'], favourite=job['source'] == 0,
                                 completed_at=now().isoformat(timespec='seconds'))
        config.cross_set(ROTATION_PATH + '.State', states)
    if equipment is not None:
        equipment.apply_pending()
    manager.finish_rotation()
    return changes


def recover_reading(runner, mode):
    """在选关导航之前退出已登记的读取页面，避免好感弹窗被当作未知界面。

    Pages:
        in: 中断的好感/角色详情，或原页面
        out: 已知读取页面返回编队；其他页面不操作
    """
    config = runner.campaign.config
    saved = config.cross_get(TRAINING_PATH, {})
    if (isinstance(saved, dict) and saved.get('reading')
            and supported(config.task.command, mode, runner.folder, runner.stage)):
        manager = FleetManagement(config=config, device=runner.device)
        FleetTrainingReader(manager).recover_page()


def training_only(runner, battle, mode):
    """仅培养调度也实读选船页舰名与心情；达标才执行同号互换。

    Pages:
        in: 普通选关页
        out: 原选关页，或按原机制延迟任务
    """
    from module.campaign.fleet_rotation import _required, mark_morale_checked
    from module.campaign.fleet_rotation_emotion import RotationEmotion
    config = runner.campaign.config
    context = runner.__dict__.setdefault('_fleet_rotation_context', {})
    if context.get('task') != config.task.command:
        context.clear()
        context['task'] = config.task.command
    restore_context(config, context)
    selected_only = config.cross_get(ROTATION_PATH + '.SelectedOnly', False) is True
    rules = parse_rules(config.cross_get(ROTATION_PATH + '.Rules', '{}'))
    selected = {role: actual for role, actual in active_fleets(config).items()
                if rules.get(str(actual), {}).get('slots')
                and (rules[str(actual)].get('sources') or rules[str(actual)].get('favourite')
                     or (goals(config) and config.cross_get('FleetInfo.FleetTraining.StopOnComplete', False) is True))
                and _required(runner.campaign.emotion, role, battle)[1] is not None}
    if not selected:
        return False
    book = runner.campaign.emotion.map_is_2x_book
    runner.campaign.emotion = RotationEmotion(config, context, rules, selected)
    runner.campaign.emotion.map_is_2x_book = book
    check_due = due(config, context)
    equipment_pending = (config.cross_get(EQUIPMENT_PATH + '.Enabled', False)
                         and config.cross_get(EQUIPMENT_PATH + '.State', {}))
    if not check_due and not state(config)['pending'] and not equipment_pending:
        return False
    manager = FleetManagement(config=config, device=runner.device)
    session = TrainingSession(runner, manager, context, rules, selected)
    if config.cross_get(EQUIPMENT_PATH + '.Enabled', False) and config.cross_get(EQUIPMENT_PATH + '.State', {}):
        equipment = FleetRotationEquipment(manager)
        equipment.recover_page()
    if session.saved.get('reading'):
        session.reader.recover_page()
    if check_due or session.saved['pending']:
        # 确认后、保存前中断时两边旧记录都可能过时，恢复前必须实读双方。
        recovery_fleets = {job[side] for job in session.saved['pending'].values() for side in ('fleet', 'source')
                           if job[side] > 0}
        inventory = set(selected.values()) | recovery_fleets
        result = session.reader.inventory(inventory,
            slots={fleet: rules[str(fleet)]['slots'] for fleet in selected.values()})
        snapshots = {fleet: recorded_morale(result, fleet) for fleet in inventory}
        config.cross_set_many(calibration_changes(config.data, snapshots, now()))
        runner.campaign.emotion.calibrate_selected(snapshots)
        context['scanned'] = True
        context['training_selected_only'] = selected_only
        if equipment_pending:
            FleetRotationEquipment(manager).apply_pending()
        session.process(fresh=True, force=True)
        mark_morale_checked(config, runner.campaign.emotion, selected, battle, context)
    elif equipment_pending:
        FleetRotationEquipment(manager).apply_pending()
    manager.finish_rotation()
    manager._commit_formation()
    from module.dorm.fleet_rotation import rest_after_rotation
    rest_after_rotation(manager, session.replaced_fleets, committed=True)
    if check_due or session.changes:
        notify_training(config, rules, selected, session.changes)
    config.update()
    runner.config.update()
    runner.campaign.emotion = RotationEmotion(config, context, rules, selected)
    runner.campaign.emotion.map_is_2x_book = book
    runner.campaign.ensure_campaign_ui(name=runner.stage, mode=mode, skip_first_screenshot=False)
    runner.campaign.map_get_info()
    return True


def after_battle_due(runner, mode):
    from module.campaign.fleet_rotation import _required, morale_due
    config = runner.campaign.config
    if (not supported(config.task.command, mode, runner.folder, runner.stage)
            or config.Campaign_Mode != 'normal'
            or (not goals(config) and config.cross_get(ROTATION_PATH + '.Enabled', False) is not True)):
        return False
    rules = parse_rules(config.cross_get(ROTATION_PATH + '.Rules', '{}'))
    selected = {role: actual for role, actual in active_fleets(config).items()
                if rules.get(str(actual), {}).get('slots')
                and (rules[str(actual)].get('sources') or rules[str(actual)].get('favourite')
                     or (goals(config) and config.cross_get('FleetInfo.FleetTraining.StopOnComplete', False) is True))
                and _required(runner.campaign.emotion, role, runner.campaign._map_battle)[1] is not None}
    context = runner.__dict__.get('_fleet_rotation_context', {})
    mood = config.cross_get(ROTATION_PATH + '.Enabled', False) is True
    return bool(selected) and (due(config, context)
        or (mood and morale_due(runner.campaign.emotion, selected, runner.campaign._map_battle, context)))
