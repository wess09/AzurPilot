"""智能换船的规则、轮换进度及普通战役心情映射，不操作设备。"""

from copy import deepcopy
import json
import re

from module.combat.emotion_state import EmotionRecoveryState


SUPPORTED_TASKS = {'Main', 'Main2', 'Main3', 'Main4', 'Main5', 'Event', 'Event2',
                   'EventA', 'EventB', 'EventC', 'EventD'}
ROTATION_PATH = 'FleetInfo.FleetRotation'
ACTIVE_ROLES = {'fleet1_all_fleet2_standby': (1,), 'fleet1_standby_fleet2_all': (2,),
                'fleet1_mob_fleet2_boss': (1, 2), 'fleet1_boss_fleet2_mob': (1, 2)}


def parse_rules(value):
    """只接受六队各自的舰位和候补队列表；空映射即全部不变。"""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError) as exc:
            raise ValueError('智能换船规则必须为JSON对象') from exc
    if not isinstance(value, dict):
        raise ValueError('智能换船规则必须为对象')
    rules = {}
    for key, entry in value.items():
        if key not in tuple(str(number) for number in range(1, 7)) or not isinstance(entry, dict):
            raise ValueError('智能换船仅支持第一至第六水面舰队')
        if set(entry) - {'slots', 'sources', 'favourite'}:
            raise ValueError('智能换船规则含未知字段')
        fields = {}
        for field in ('slots', 'sources'):
            items = entry.get(field, [])
            if (not isinstance(items, list) or any(type(item) is not int or not 1 <= item <= 6 for item in items)
                    or len(items) != len(set(items))):
                raise ValueError('舰位和候补舰队必须为1至6的不重复整数列表')
            fields[field] = sorted(items)
        if int(key) in fields['sources']:
            raise ValueError('候补舰队不能包含目标舰队自身')
        if 'favourite' in entry:
            if type(entry['favourite']) is not bool:
                raise ValueError('常用候补必须为布尔开关')
            fields['favourite'] = entry['favourite']
        rules[key] = fields
    return rules


def hard_event_stage(name):
    """活动C/D、HT与EX不使用港区普通编队，不能按文件中的normal默认值推断。"""
    return bool(re.match(r'^(?:[cd]\d|ht\d|ex(?:_ex)?$)', str(name).strip().lower()))


def supported(task, mode, folder, stage=''):
    return (task in SUPPORTED_TASKS and mode == 'normal'
            and (folder == 'campaign_main' or (str(folder).startswith('event_') and not hard_event_stage(stage))))


def active_fleets(config):
    """将战斗角色1/2映射到港区实际舰队号，待命角色不触发换船。"""
    return {role: getattr(config, f'Fleet_Fleet{role}')
            for role in ACTIVE_ROLES.get(config.Fleet_FleetOrder, ())
            if type(getattr(config, f'Fleet_Fleet{role}')) is int and 1 <= getattr(config, f'Fleet_Fleet{role}') <= 6}


def rank_sources(rule, readings, needed=0, *, selected_only=False):
    """候补按整队或勾选舰位的最低实测心情降序，同值按编号升序。"""
    available = []
    for source in rule['sources']:
        ships = readings.get(source, {})
        minimum = minimum_morale({slot: ships.get(slot) for slot in rule['slots']} if selected_only else ships)
        if minimum is not None and minimum >= needed and all(slot in ships for slot in rule['slots']):
            available.append((source, minimum))
    return [source for source, _ in sorted(available, key=lambda item: (-item[1], item[0]))]


def recorded_morale(result, fleet):
    """读取舰船信息中的实际舰位；旧版无舰位数据不能按数组顺序猜位置。"""
    readings = {}
    if not isinstance(result, dict):
        return readings
    for category in ('main', 'vanguard'):
        for ship in result.get(category, {}).get(str(fleet), []):
            slot = ship.get('slot')
            if type(slot) is int and ship.get('occupied', True):
                if slot in readings:
                    return {}
                readings[slot] = ship.get('emotion')
    return readings


def begin_round(rule, previous, ranked_sources=None):
    """实测优先级决定本轮来源；未完成的一轮保持来源和已完成舰位。"""
    previous = deepcopy(previous) if isinstance(previous, dict) else {}
    if previous.get('pending'):
        raise ValueError('上次换船结果未确认，请核对游戏编队后清空轮换记录')
    if previous.get('source') is not None:
        if previous.get('policy') != 'same_slot_morale_v1':
            raise ValueError('旧版轮换记录不能按新舰位策略续接，请核对编队后清空记录')
        if previous.get('rule') != rule:
            raise ValueError('未完成轮换期间规则发生变化，请先核对编队并清空轮换记录')
        return previous
    sources = rule['sources'] if ranked_sources is None else ranked_sources
    if not rule['slots'] or not sources:
        return None
    last = previous.get('last_source')
    return dict(last_source=last, source=sources[0], done=[], pending=None, rule=deepcopy(rule),
                policy='same_slot_morale_v1')


def minimum_morale(ships):
    """仅对实际占用舰位取最低心情；未知读数不能冒充实测值。"""
    values = list(ships.values())
    if not values or any(type(value) is not int or not 0 <= value <= 150 for value in values):
        return None
    return min(values)


def calibration_changes(data, readings, stamp):
    """将实际舰队最低心情联动到普通主线/活动任务，重建数值、时间与相位。"""
    changes = {}
    for task, values in data.items():
        if task not in SUPPORTED_TASKS or values.get('Campaign', {}).get('Mode') != 'normal':
            continue
        if task.startswith('Event') and hard_event_stage(values.get('Campaign', {}).get('Name', '')):
            continue
        fields = values.get('Emotion', {})
        for role in (1, 2):
            actual = values.get('Fleet', {}).get(f'Fleet{role}')
            if type(actual) is not int or actual not in readings:
                continue
            prefix = f'Fleet{role}'
            base = f'{task}.Emotion.{prefix}'
            value = minimum_morale(readings[actual])
            # 互换改变了实体，即使本次读数未知也不能沿用旧船的恢复相位。
            changes[base + 'RecoveryState'] = None
            if value is None:
                continue
            try:
                state = EmotionRecoveryState.calibrate(value, stamp, fields[prefix + 'Recover'],
                                                       fields[prefix + 'Oath'], fields[prefix + 'Onsen'])
            except (ValueError, KeyError):
                continue
            changes.update({base + 'Value': value, base + 'Record': stamp,
                            base + 'RecoveryState': state.export()})
            changes[f'{task}.Emotion.RecoveryWait'] = None
    # 公海只在所有关联任务明确使用同一个实际舰队时同步；否则使旧相位失效。
    public = data.get('General', {}).get('PublicEmotion', {})
    if public.get('Enable'):
        tasks = [task.strip() for task in str(public.get('Tasks', '')).split(',') if task.strip()]
        actuals = set()
        for task in tasks:
            values = data.get(task, {})
            roles = ACTIVE_ROLES.get(values.get('Fleet', {}).get('FleetOrder'), ())
            if (task not in SUPPORTED_TASKS or values.get('Campaign', {}).get('Mode') != 'normal' or len(roles) != 1
                    or (task.startswith('Event') and hard_event_stage(values.get('Campaign', {}).get('Name', '')))):
                actuals.add(None)
            else:
                actuals.add(values['Fleet'].get(f'Fleet{roles[0]}'))
        if actuals.intersection(readings):
            base = 'General.PublicEmotion.Fleet'
            changes[base + 'RecoveryState'] = None
            if len(actuals) == 1:
                value = minimum_morale(readings[next(iter(actuals))])
                if value is not None:
                    state = EmotionRecoveryState.calibrate(value, stamp, public['FleetRecover'],
                                                           public['FleetOath'], public['FleetOnsen'])
                    changes.update({base + 'Value': value, base + 'Record': stamp,
                                    base + 'RecoveryState': state.export()})
    return changes
