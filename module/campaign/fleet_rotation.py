"""普通主线与活动出击前的智能换船；一轮只使用一个候补舰队。"""

from copy import deepcopy

from module.combat.emotion import Emotion
from module.campaign.fleet_rotation_emotion import RotationEmotion, selected_morale
from module.config.time_source import now
from module.device.control import control_interval
from module.equipment.fleet_rotation import FleetRotationEquipment
from module.exception import FleetManagementError, GameStuckError, GameTooManyClickError, RequestHumanTakeover
from module.logger import logger
from module.retire.fleet_management import FleetManagement
from module.runtime.fleet_rotation import (ROTATION_PATH, active_fleets, begin_round, calibration_changes,
                                         minimum_morale, parse_rules, rank_sources, recorded_morale, supported)
from module.runtime.fleet_equipment import EQUIPMENT_PATH
from module.runtime.fleet_training import (due, goals, mark_checked,
                                           persist_context, restore_context)
from module.campaign.fleet_training_notify import notify_training


def _required(emotion, role, battle):
    order = emotion.config.Fleet_FleetOrder
    counts = {'fleet1_mob_fleet2_boss': (max(0, battle - 1), 1),
              'fleet1_boss_fleet2_mob': (1, max(0, battle - 1)),
              'fleet1_all_fleet2_standby': (battle, 0), 'fleet1_standby_fleet2_all': (0, battle)}[order]
    tracker = emotion.public_fleet if emotion.using_public else emotion.fleets[role - 1]
    if counts[role - 1] == 0:
        return tracker, None
    reduce = counts[role - 1] * emotion.reduce_per_battle_before_entering
    if tracker.control == 'keep_exp_bonus':
        reduce = min(29, reduce)
    return tracker, tracker.limit + reduce


def morale_due(emotion, selected, battle, context):
    """只在现有控制线需要等待/换船时触发，刚核对过的低心情不重复扫描。"""
    emotion.update()
    for role, fleet in selected.items():
        tracker, needed = _required(emotion, role, battle)
        value = (emotion.training_lower(role) if isinstance(emotion, RotationEmotion)
                 else tracker.lower if tracker.state is not None else None)
        if value is None:
            return True
        verified = context.get('morale_low', {}).get(str(role))
        if needed is not None and value <= needed and verified != dict(fleet=fleet, needed=needed):
            return True
    return False


def mark_morale_checked(config, emotion, selected, battle, context):
    low = {}
    for role, fleet in selected.items():
        tracker, needed = _required(emotion, role, battle)
        value = (emotion.training_lower(role) if isinstance(emotion, RotationEmotion)
                 else tracker.lower if tracker.state is not None else None)
        if needed is not None and value is not None and value <= needed:
            low[str(role)] = dict(fleet=fleet, needed=needed)
    context['morale_low'] = low
    persist_context(config, context)


@control_interval((0.1, 0.3))
def preflight_rotation(runner, battle, mode):
    """在原有心情检查之前轮换，恢复选关页后仍走正常心情及入场流程。

    Pages:
        in: 普通主线或活动选关页、自动搜索续战菜单
        out: 已操作时返回当前任务选关页；未操作时保持原页面
    """
    campaign = runner.campaign
    config = campaign.config
    mood_enabled = config.cross_get(ROTATION_PATH + '.Enabled', False) is True
    if ((not mood_enabled and not goals(config))
            or not supported(config.task.command, mode, runner.folder, runner.stage)
            or campaign.config.Campaign_Mode != 'normal'):
        if isinstance(campaign.emotion, RotationEmotion):
            book = campaign.emotion.map_is_2x_book
            campaign.emotion = Emotion(config)
            campaign.emotion.map_is_2x_book = book
        return False
    if not mood_enabled:
        from module.campaign.fleet_training import training_only
        return training_only(runner, battle, mode)
    try:
        rules = parse_rules(config.cross_get(ROTATION_PATH + '.Rules', '{}'))
    except ValueError as exc:
        raise FleetManagementError(str(exc)) from exc
    active = active_fleets(config)
    states = deepcopy(config.cross_get(ROTATION_PATH + '.State', {}))
    if not isinstance(states, dict):
        states = {}
    recovering, recovery_fleets = set(), set()
    for target, progress in states.items():
        if isinstance(progress, dict) and (progress.get('pending') or progress.get('rescan') or
                (progress.get('source') and (not progress.get('paused') or
                 progress.get('rule') != rules.get(target) or progress.get('policy') != 'same_slot_morale_v1'))):
            recovering.add(int(target))
            recovery_fleets.add(int(target))
            if progress.get('source'):
                recovery_fleets.add(progress['source'])
            states[target] = {'rescan': True}
    selected = {role: actual for role, actual in active.items()
                if rules.get(str(actual), {}).get('slots')
                and (rules[str(actual)].get('sources') or rules[str(actual)].get('favourite')
                     or (goals(config) and config.cross_get('FleetInfo.FleetTraining.StopOnComplete', False) is True))
                and _required(campaign.emotion, role, battle)[1] is not None}
    manager = None
    emotion = campaign.emotion
    emotion.update()
    visited = False
    context = runner.__dict__.setdefault('_fleet_rotation_context', {})
    task = config.task.command
    if context.get('task') != task:
        context.clear()
        context['task'] = task
    signature = dict(rules=rules, active=active, mode=config.Emotion_Mode,
                     selected_only=config.cross_get(ROTATION_PATH + '.SelectedOnly', False),
                     recovery=[(emotion.public_fleet if emotion.using_public else tracker).recover
                               for tracker in emotion.fleets],
                     public=emotion.using_public)
    if context.get('signature') != signature:
        context['signature'] = deepcopy(signature)
        context['scanned'] = False
        # 已确认的舰位心情仍由实际舰队、舰位和恢复设置逐项验证；
        # 仅切换计算范围不能清空它并迫使间隔内再次扫描。
    restore_context(config, context)
    book = emotion.map_is_2x_book
    emotion = RotationEmotion(config, context, rules, selected)
    emotion.map_is_2x_book = book
    campaign.emotion = emotion
    if recovering:
        logger.info('自动清理上轮未完成记录，按实际编队重新扫描，不重复已恢复心情的舰位')
        config.cross_set(ROTATION_PATH + '.State', states)
        context['scanned'] = False
        context.pop('portraits', None)
    scan_fleets = set(selected.values()) | recovery_fleets
    from module.runtime.fleet_training import state
    pending = state(config)['pending']
    scan_fleets.update(job[side] for job in pending.values() for side in ('fleet', 'source') if job[side] > 0)
    training_due = due(config, context)
    mood_due = morale_due(emotion, selected, battle, context)
    fresh = bool(scan_fleets) and (training_due or mood_due or bool(recovering) or bool(pending))
    checked_this_round = fresh
    current_fleet = None
    equipment_enabled = config.cross_get(EQUIPMENT_PATH + '.Enabled', False) is True
    equipment_used = False
    replaced_fleets = set()
    full_scanned = False
    changes = []
    try:
        fresh_readings = {}
        if equipment_enabled and config.cross_get(EQUIPMENT_PATH + '.State', {}):
            manager = FleetManagement(config=config, device=runner.device)
            FleetRotationEquipment(manager).recover_page()
        if fresh:
            if manager is None:
                manager = FleetManagement(config=config, device=runner.device)
            if goals(config):
                from module.runtime.fleet_training import state
                if state(config).get('reading'):
                    from module.retire.fleet_training import FleetTrainingReader
                    FleetTrainingReader(manager).recover_page()
            visited = True
            from module.campaign.fleet_training import FleetTrainingReader
            FleetTrainingReader(manager).inventory(scan_fleets,
                slots={fleet: rules[str(fleet)]['slots'] for fleet in selected.values()})
            result = config.cross_get('FleetInfo.FleetInfo.Result', {})
            fresh_readings = {fleet: recorded_morale(result, fleet)
                              for fleet in scan_fleets}
            config.cross_set_many(calibration_changes(config.data,
                {fleet: values for fleet, values in fresh_readings.items() if values}, now()))
            emotion.calibrate_selected(fresh_readings)
            context['scanned'] = True
            context['portraits'] = manager.__dict__.get('_slot_portraits', {})
            if not goals(config):
                mark_checked(config, context)
            for fleet in recovering:
                states.pop(str(fleet), None)
            config.cross_set(ROTATION_PATH + '.State', states)
        if equipment_enabled and config.cross_get(EQUIPMENT_PATH + '.State', {}):
            if manager is None:
                manager = FleetManagement(config=config, device=runner.device)
            visited = True
            FleetRotationEquipment(manager).apply_pending()
            equipment_used = True
        training = None
        if goals(config):
            from module.campaign.fleet_training import TrainingSession
            training = TrainingSession(runner, manager or FleetManagement(config=config, device=runner.device),
                                       context, rules, selected)
            manager = training.manager
            if training.process(fresh=fresh, force=training_due):
                visited = True
                equipment_used |= training.equipment_used
                result = config.cross_get('FleetInfo.FleetInfo.Result', {})
                fresh_readings = {number: recorded_morale(result, number) for number in range(1, 7)}
            full_scanned = training.sources_refreshed
            replaced_fleets.update(training.replaced_fleets)
            changes.extend(training.changes)
        for role, fleet in selected.items():
            current_fleet = fleet
            if training is not None and fleet in training.replaced_fleets:
                continue
            # 前一个角色可能刚从本角色的实际舰队换走舰船，不能继续使用旧快照。
            emotion.update()
            rule = training.rotation_rule(fleet) if training is not None else rules[str(fleet)]
            if not rule['slots']:
                continue
            previous = states.get(str(fleet), {})
            if not isinstance(previous, dict):
                previous = {}
            tracker, needed = _required(emotion, role, battle)
            if needed is None:
                continue
            logger.attr(f'第{fleet}舰队培养最低心情/换船要求', f'{emotion.training_lower(role)}/{needed}')
            continuing = bool(previous.get('source') or previous.get('pending'))
            if not fresh and not continuing:
                continue
            if fresh and not continuing:
                value = selected_morale(fresh_readings[fleet], rule['slots'])
                if value is None or value > needed:
                    continue
            visited = True
            if manager is None:
                manager = FleetManagement(config=config, device=runner.device)
                manager._slot_portraits = context.get('portraits', {})
            if not full_scanned:
                logger.info('已到心情保留值，完整扫描全舰队后再排序候补')
                manager.finish_rotation()
                manager.run(update_emotion=True)
                full_scanned = True
                if training is not None:
                    training.inventory_fleets.update(range(1, 7))
                    training.sources_refreshed = True
            snapshots = manager.prepare_rotation(fleet, slots=rule['slots'], scan=False)
            readings = snapshots[fleet]
            emotion.calibrate_selected(snapshots)
            minimum = selected_morale(readings, rule['slots'])
            if minimum is None:
                logger.warning('培养舰位实际心情未读全，不执行换船，由心情检查决定是否等待或停止')
                manager.finish_rotation()
                continue
            config.cross_set_many(calibration_changes(config.data, snapshots, now()))
            logger.attr(f'第{fleet}舰队培养舰位最低心情', minimum)
            if not continuing and minimum > needed:
                manager.finish_rotation()
                continue
            if fleet in recovering:
                # 出错前可能已经换入；重新实测后只处理仍不足的已勾选舰位。
                rule = dict(rule, slots=[slot for slot in rule['slots'] if readings.get(slot, 150) <= needed])
            if continuing:
                try:
                    progress = begin_round(rule, previous)
                except ValueError as exc:
                    raise FleetManagementError(str(exc)) from exc
            else:
                order = rank_sources(rule, snapshots, needed, selected_only=emotion.selected_only)
                if training is not None:
                    order = training.filter_sources(order, rule, fleet)
                progress = begin_round(rule, previous, order)
                if progress is None:
                    if rule.get('favourite'):
                        from module.campaign.fleet_training import rotate_favourite_fallback
                        fallback = rotate_favourite_fallback(runner, manager, context, rules, selected, fleet,
                                                            rule, snapshots, needed, states, training)
                        changes.extend(fallback)
                        if fallback:
                            replaced_fleets.add(fleet)
                            equipment_used |= equipment_enabled
                        # 本轮逐舰位候补/常用选择结束，心情仍低则沿用原等待逻辑。
                        fresh = False
                        continue
                    logger.warning('候补队没有满足心情及对应舰位的舰船，保留当前编队并沿用原心情检查')
                    manager.finish_rotation()
                    continue
                logger.attr('候补队心情优先级', order)
            source = progress['source']
            states[str(fleet)] = progress
            config.cross_set(ROTATION_PATH + '.State', states)
            logger.hr(f'智能换船：第{fleet}舰队使用候补第{source}舰队', level=1)
            equipment = None
            remaining = [slot for slot in rule['slots'] if slot not in progress['done']]
            if equipment_enabled and remaining:
                equipment = FleetRotationEquipment(manager)
                equipment.clear_outgoing(fleet, remaining)
                equipment_used = True
            paused = False
            for slot in rule['slots']:
                if slot in progress['done']:
                    continue
                if config.cross_get(ROTATION_PATH + '.Enabled', False) is not True:
                    paused = True
                    break
                source_slot = slot
                # 先记下即将执行的互换。进程中断后不能猜测已交换还是尚未交换。
                progress['pending'] = dict(slot=slot, source_slot=source_slot)
                config.cross_set(ROTATION_PATH + '.State', states)
                from module.runtime.fleet_training import ships
                before = config.cross_get('FleetInfo.FleetInfo.Result', {})
                outgoing = ships(before, fleet).get(slot, {}).get('name') or '未确认舰名'
                incoming = ships(before, source).get(slot, {}).get('name') or '未确认舰名'
                snapshots = manager.rotate_slot(source, slot, fleet)
                config.cross_set_many(calibration_changes(config.data,
                    {number: snapshots[number] for number in (fleet, source)}, now()))
                emotion.calibrate_selected({number: snapshots[number] for number in (fleet, source)})
                changes.append(dict(fleet=fleet, slot=slot, source=source, incoming=incoming, outgoing=outgoing))
                progress['done'].append(slot)
                progress['pending'] = None
                config.cross_set(ROTATION_PATH + '.State', states)
            # 最后一个舰位已刷新当前排，直接使用累计快照，不再重扫前后排或详情。
            readings = {number: snapshots[number] for number in (fleet, source)}
            if any((selected_morale(values, rule['slots']) if emotion.selected_only else minimum_morale(values))
                   is None for values in readings.values()):
                raise FleetManagementError('互换后心情未读全，下次自动重新扫描实际编队')
            if equipment is not None:
                # 即使中途关闭换船，也先补回已经卸装的当前舰位，避免空装出击。
                equipment.apply_pending()
            if not paused:
                states[str(fleet)] = dict(last_source=source, completed_at=now().isoformat(timespec='seconds'))
                replaced_fleets.add(fleet)
            else:
                progress['paused'] = True
            config.cross_set(ROTATION_PATH + '.State', states)
            manager.finish_rotation()
            context['portraits'] = manager.__dict__.get('_slot_portraits', {})
            fresh = False
            book = emotion.map_is_2x_book
            emotion = RotationEmotion(config, context, rules, selected)
            emotion.map_is_2x_book = book
            # 本轮到此结束，心情仍低则交给原有延迟逻辑，不连续轮换下一来源。
        if visited:
            manager.finish_rotation()
            if equipment_used:
                manager._commit_formation()
            from module.dorm.fleet_rotation import rest_after_rotation
            rest_after_rotation(manager, replaced_fleets, committed=equipment_used)
            config.update()
            runner.config.update()
            campaign.emotion = RotationEmotion(config, context, rules, selected)
            campaign.emotion.map_is_2x_book = emotion.map_is_2x_book
            campaign.ensure_campaign_ui(name=runner.stage, mode=mode, skip_first_screenshot=False)
            campaign.map_get_info()
            if checked_this_round or changes:
                notify_training(config, rules, selected, changes)
        mark_morale_checked(config, campaign.emotion, selected, battle, context)
        if checked_this_round and not goals(config):
            mark_checked(config, context)
        return visited
    except (GameStuckError, GameTooManyClickError, RequestHumanTakeover) as exc:
        changed = {number: {1: None} for target, progress in states.items() if isinstance(progress, dict)
                   and progress.get('source') and (progress.get('done') or progress.get('pending'))
                   for number in (int(target), progress['source'])}
        if changed:
            config.cross_set_many(calibration_changes(config.data, changed, now()))
        if current_fleet is not None:
            states[str(current_fleet)] = {'rescan': True}
        config.cross_set(ROTATION_PATH + '.State', states)
        context['scanned'] = False
        context.pop('portraits', None)
        raise FleetManagementError(f'智能换船本次未完成，下次自动清理并重扫实际编队：{exc}') from exc
