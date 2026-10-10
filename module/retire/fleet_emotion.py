"""只利用舰队扫描已有结果学习恢复相位；不触发设备、OCR 或配置读取。"""

from datetime import datetime

from module.combat.emotion_state import EmotionRecoveryState, MAX_OBSERVATION_US, time_us


# 仅接纳已核实按请求现截的后端。流式或缓存后端没有采集时间，不能猜延迟。
TIMED_METHODS = {'ADB', 'ADB_nc', 'uiautomator2', 'aScreenCap', 'aScreenCap_nc'}
CAMPAIGN_TASKS = {'Main', 'Main2', 'Main3', 'Main4', 'Main5', 'Event', 'Event2',
                  'EventA', 'EventB', 'EventC', 'EventD', 'WarArchives'}
ORDERS = {'fleet1_all_fleet2_standby': (1,), 'fleet1_standby_fleet2_all': (2,),
          'fleet1_mob_fleet2_boss': (1, 2), 'fleet1_boss_fleet2_mob': (1, 2)}


def screenshot_window(device):
    """已有相邻帧完成时间包围本次现截；缺少证据时跳过，不读取时钟。"""
    history = vars(device).get('screenshot_deque')
    config = vars(device).get('config')
    if history is None or len(history) < 2 or config is None:
        return None
    method = getattr(device, 'screenshot_method_override', '') or getattr(config, 'Emulator_ScreenshotMethod', '')
    if method not in TIMED_METHODS or not getattr(config, 'Error_SaveError', False):
        return None
    before, current = history[-2], history[-1]
    if current.get('image') is not getattr(device, 'image', None):
        return None
    begin, end = before.get('time'), current.get('time')
    if not isinstance(begin, datetime) or not isinstance(end, datetime):
        return None
    try:
        if not 0 <= time_us(end) - time_us(begin) <= MAX_OBSERVATION_US:
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    return begin, end


def _mapping(task, values):
    """普通战役使用配置中的港区舰队；困难编成和自动换船任务不推断归属。"""
    if (task not in CAMPAIGN_TASKS or values.get('Campaign', {}).get('Mode') != 'normal' or
            'calculate' not in str(values.get('Emotion', {}).get('Mode', ''))):
        return None
    fleet = values.get('Fleet', {})
    active = ORDERS.get(fleet.get('FleetOrder'))
    if active is None:
        return None
    ids = {i: fleet.get(f'Fleet{i}') for i in (1, 2)}
    if any(type(ids[i]) is not int or not 1 <= ids[i] <= 6 for i in active):
        return None
    if ids[1] == ids[2]:
        return None
    return ids, active


def learn_fleet_emotion(config, result, windows, known_names):
    """向既有保存事务加入学到的三字段；只读内存快照，不另行保存。"""
    if not known_names or not all(windows.get(category) for category in ('vanguard', 'main')):
        return 0
    data = getattr(config, 'data', {})
    observations = {}
    for number in range(1, 7):
        groups, names = [], []
        for category in ('vanguard', 'main'):
            ships = result.get(category, {}).get(str(number), [])
            if len(ships) != 3:
                break
            if any(ship.get('name') not in known_names or type(ship.get('emotion')) is not int or
                   not 0 <= ship['emotion'] <= 150 for ship in ships):
                break
            names.extend(ship['name'] for ship in ships)
            groups.append((min(ship['emotion'] for ship in ships), *windows[category]))
        else:
            if len(set(names)) == 6:
                observations[number] = groups
    if not observations:
        return 0
    shared = data.get('General', {}).get('PublicEmotion', {})
    shared_tasks = {item.strip() for item in str(shared.get('Tasks') or '').split(',') if item.strip()}
    uses_shared = shared.get('Enable') is True and bool(shared_tasks)
    targets = []
    mappings = {task: _mapping(task, values) for task, values in data.items() if isinstance(values, dict)}
    for task, mapping in mappings.items():
        if mapping is None or (uses_shared and task in shared_tasks):
            continue
        ids, _ = mapping
        for i, number in ids.items():
            if type(number) is int and number in observations:
                targets.append((f'{task}.Emotion.Fleet{i}', data[task]['Emotion'], f'Fleet{i}', number, [task]))
    if uses_shared:
        shared_ids = set()
        for task in shared_tasks:
            mapping = mappings.get(task)
            if mapping is None or len(mapping[1]) != 1:
                break
            shared_ids.add(mapping[0][mapping[1][0]])
        else:
            if len(shared_ids) == 1:
                targets.append(('General.PublicEmotion.Fleet', shared, 'Fleet', shared_ids.pop(), sorted(shared_tasks)))
    learned = 0
    for path, fields, prefix, number, tasks in targets:
        if number not in observations or fields.get(prefix + 'Onsen') is not False:
            continue
        try:
            record = fields[prefix + 'Record']
            record = datetime.fromisoformat(record) if isinstance(record, str) else record
            state = EmotionRecoveryState.restore(fields.get(prefix + 'RecoveryState'), fields[prefix + 'Value'],
                                                 record, fields[prefix + 'Recover'], fields[prefix + 'Oath'], False)
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
        if not state.observe(observations[number]):
            continue
        config.modified.update({path + 'Value': state.value, path + 'Record': state.record,
                                path + 'RecoveryState': state.export()})
        # 同一保存事务重新读取磁盘时还需核对舰队映射，避免扫描期间改配置串队。
        guards = {'General.PublicEmotion.Enable': shared.get('Enable'),
                  'General.PublicEmotion.Tasks': shared.get('Tasks')}
        for task in tasks:
            guards.update({f'{task}.Fleet': data[task].get('Fleet'),
                           f'{task}.Campaign.Mode': data[task]['Campaign']['Mode'],
                           f'{task}.Emotion.Mode': data[task]['Emotion']['Mode']})
        if '_emotion_observation_guards' not in vars(config):
            config._emotion_observation_guards = {}
        config._emotion_observation_guards[path] = guards
        learned += 1
    return learned
