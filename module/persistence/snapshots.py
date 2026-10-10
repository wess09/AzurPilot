"""将月度统计和舰船快照投影到业务表，保留扩展字段与字段存在性。"""
from module.persistence.database import register_instance
from module.persistence.values import normalize, read_value, scalar, write_value

MONTH_FIELDS = (
    'battle_count', 'akashi_encounters', 'akashi_ap', 'akashi_ap_entries', 'ap_snapshots',
    'last_ap_notification', 'yellow_coin_snapshots', 'coins_snapshots', 'coins_history_version',
    'coins_cleanup_version', 'meow_battle_raw_count', 'meow_battle_count', 'meow_round_times',
    'meow_battle_times', 'meow_hazard_stats', 'siren_research_devices', 'siren_research_device_entries',
    'commission_income_entries', 'research_drop_entries', 'gem_commission_entries', 'running_gem_commissions',
)
SHIP_FIELDS = ('last_check_time', 'target_level', 'fleet_index', 'battle_count_at_check', 'ships',
               'battle_times', 'meow_battle_times', 'round_times', 'daily_stats')
MONTH_SCALARS = (
    ('battle_count', 'battle_count', 'I'), ('akashi_encounters', 'akashi_encounters', 'I'),
    ('akashi_ap', 'akashi_ap', 'I'), ('meow_battle_raw_count', 'meow_battle_raw_count', 'I'),
    ('meow_battle_count', 'meow_effective_rounds', 'R'),
    ('coins_history_version', 'coins_history_version', 'I'), ('coins_cleanup_version', 'coins_cleanup_version', 'I'),
)
SHIP_SCALARS = (
    ('last_check_time', 'checked_at', 'T'), ('target_level', 'target_level', 'I'),
    ('fleet_index', 'fleet_index', 'I'), ('battle_count_at_check', 'battle_count_at_check', 'I'),
)
HAZARD_FIELDS = (
    ('battle_raw_count', 'battle_raw_count', 'I'), ('effective_rounds', 'effective_rounds', 'R'),
    ('round_times', None, 'list'), ('battle_times', None, 'list'),
    ('akashi_encounters', 'akashi_encounters', 'I'), ('akashi_ap', 'akashi_ap', 'I'),
)
SHIP_ROW_FIELDS = tuple((name, name, 'I') for name in ('position', 'level', 'current_exp', 'total_exp'))
SHIP_DAILY_FIELDS = (('total_run_time', 'total_run_time', 'R'), ('total_exp_gained', 'total_exp_gained', 'I'),
                     ('battle_count', 'battle_count', 'I'), ('exp_per_hour', 'exp_per_hour', 'R'))
GROUP_FIELDS = (('samples', None, 'list'), ('average', 'average_seconds', 'R'))
FAMILIES = {
    'akashi_ap_entries': ('akashi_ap_purchases', (('ts', 'ts', 'T'), ('amount', 'amount', 'I'),
        ('base', 'base', 'I'), ('count', 'purchase_count', 'I'), ('source', 'source', 'T'))),
    'siren_research_device_entries': ('siren_device_events', (('ts', 'ts', 'T'),
        ('source', 'source', ('cl1', 'meow')), ('hazard_level', 'hazard_level', 'I'))),
    'ap_snapshots': ('action_point_snapshots', (('ts', 'ts', 'T'), ('ap', 'ap', 'I'),
        ('ap_total', 'ap_total', 'I'), ('yellow_coin', 'yellow_coin', 'I'), ('asset', 'asset', 'R'),
        ('source', 'source', 'T'), ('distance', 'distance', 'I'))),
    'yellow_coin_snapshots': ('yellow_coin_snapshots', (('ts', 'ts', 'T'),
        ('yellow_coin', 'yellow_coin', 'I'), ('source', 'source', 'T'))),
    'coins_snapshots': ('coin_snapshots', (('ts', 'ts', 'T'), ('yellow_coins', 'yellow_coin', 'I'),
        ('purple_coins', 'purple_coin', 'I'), ('source', 'source', 'T'))),
    'commission_income_entries': ('commission_income', (('ts', 'ts', 'T'),
        ('commission_count', 'commission_count', 'I'), ('items', None, 'map'), ('screenshots', None, 'list'))),
    'research_drop_entries': ('research_drops', (('ts', 'ts', 'T'), ('completed_at', 'completed_at', 'T'),
        ('imgid', 'imgid', 'T'), ('project', 'project', 'T'), ('series', 'series', 'I'), ('items', None, 'map'))),
    'gem_commission_entries': ('gem_commission_history', (('ts', 'ts', 'T'), ('duration', 'duration_hours', 'I'),
        ('reward', 'gem_reward', 'I'), ('success', 'success', 'B'))),
    'running_gem_commissions': ('running_gem_commissions', (('name', 'name', 'T'), ('duration', 'duration_hours', 'I'),
        ('create_time', 'created_at', 'T'), ('finish_time', 'finishes_at', 'T'))),
}


def presence(data, fields):
    """记录快照字段是否存在及其原始取值。"""
    return sum(1 << index for index, name in enumerate(fields) if name in data)


def project(data, fields):
    """将业务快照投影为可持久化的结构化字段。"""
    columns = {column: None for _, column, _ in fields if column}
    extra = {name: value for name, value in data.items() if name not in {field[0] for field in fields}}
    mask = 0
    for index, (name, column, kind) in enumerate(fields):
        if name not in data:
            continue
        mask |= 1 << index
        value = data[name]
        if kind in ('map', 'list'):
            valid = type(value) is (dict if kind == 'map' else list)
            stored = None
        else:
            valid, stored = scalar(value, kind)
        if valid:
            if column:
                columns[column] = stored
        else:
            extra[name] = value
    return columns, mask, extra


def insert(connection, table, data):
    """向指定原生业务表写入规范化记录。"""
    columns = ','.join(data)
    marks = ','.join('?' for _ in data)
    return connection.execute(f'INSERT INTO {table}({columns}) VALUES({marks})', tuple(data.values())).lastrowid


def save_row(connection, table, keys, data, fields, owner, *, entry=False):
    """保存快照中的单条原生表记录。"""
    if type(data) is dict:
        columns, mask, extra = project(data, fields)
        value_id = write_value(connection, value=extra, **owner) if extra else None
        kind = 'record'
    else:
        if not entry:
            raise TypeError('业务记录必须是字典')
        columns = {column: None for _, column, _ in fields if column}
        mask, kind = 0, 'value'
        value_id = write_value(connection, value=data, **owner)
    values = dict(keys, **columns, field_mask=mask, compat_value_set_id=value_id)
    if entry:
        values['entry_kind'] = kind
    return insert(connection, table, values)


def load_row(connection, row, fields, collections=None):
    """从数据库读取一条记录并恢复快照字段。"""
    if 'entry_kind' in row.keys() and row['entry_kind'] == 'value':
        return read_value(connection, row['compat_value_set_id'])
    result = {}
    for index, (name, column, kind) in enumerate(fields):
        if not row['field_mask'] & (1 << index):
            continue
        if column:
            value = row[column]
            result[name] = bool(value) if kind == 'B' and value is not None else value
        else:
            result[name] = (collections or {}).get(name, {} if kind == 'map' else [])
    if row['compat_value_set_id'] is not None:
        extra = read_value(connection, row['compat_value_set_id'])
        if type(extra) is not dict:
            raise ValueError('业务记录扩展必须是字典')
        result.update(extra)
    return result


def save_children(connection, table, row_id, record, owner):
    """将快照嵌套条目映射到关联子表。"""
    if type(record) is not dict or table not in ('commission_income', 'research_drops'):
        return
    key = 'income_id' if table == 'commission_income' else 'drop_id'
    child_table = 'commission_income_items' if table == 'commission_income' else 'research_drop_items'
    items = record.get('items')
    if type(items) is dict:
        for item, amount in items.items():
            valid, stored = scalar(amount, 'I')
            value_id = None if valid else write_value(connection, value=amount, **owner)
            insert(connection, child_table, {key: row_id, 'instance': owner['instance'], 'month': owner['month'],
                   'item': item, 'amount': stored if valid else None, 'compat_value_set_id': value_id})
    if table == 'commission_income' and type(record.get('screenshots')) is list:
        for ordinal, path in enumerate(record['screenshots']):
            valid, stored = scalar(path, 'T')
            value_id = None if valid else write_value(connection, value=path, **owner)
            insert(connection, 'commission_income_screenshots', {'income_id': row_id, 'instance': owner['instance'],
                'month': owner['month'], 'ordinal': ordinal, 'path': stored if valid else None, 'compat_value_set_id': value_id})


def load_children(connection, table, row_id):
    """读取关联子表并恢复嵌套条目。"""
    if table not in ('commission_income', 'research_drops'):
        return {}
    key = 'income_id' if table == 'commission_income' else 'drop_id'
    child_table = 'commission_income_items' if table == 'commission_income' else 'research_drop_items'
    items = {}
    for row in connection.execute(f'SELECT * FROM {child_table} WHERE {key}=? ORDER BY rowid', (row_id,)):
        items[row['item']] = read_value(connection, row['compat_value_set_id']) if row['compat_value_set_id'] is not None else row['amount']
    collections = {'items': items}
    if table == 'commission_income':
        collections['screenshots'] = [read_value(connection, row['compat_value_set_id']) if row['compat_value_set_id'] is not None else row['path']
            for row in connection.execute('SELECT * FROM commission_income_screenshots WHERE income_id=? ORDER BY ordinal', (row_id,))]
    return collections


def canonical_integer(key):
    """将合法整数值转换为数据库规范表示。"""
    try:
        value = int(key)
    except (ValueError, TypeError):
        return None
    return value if str(value) == key and -(2 ** 63) <= value < 2 ** 63 else None


def save_meow_samples(connection, samples, kind, bucket, owner):
    """保存喵箱收益统计中的独立样本。"""
    fields = (('duration', 'duration_seconds', 'R'), ('hazard_level', 'observed_hazard', 'I'))
    for ordinal, sample in enumerate(samples):
        columns = {'duration_seconds': None, 'observed_hazard': None}
        mask, hazard_present, value_id = 0, 0, None
        if type(sample) is dict:
            columns, mask, extra = project(sample, fields)
            entry_format, hazard_present = 'object', int('hazard_level' in sample)
            value_id = write_value(connection, value=extra, **owner) if extra else None
        elif type(sample) in (int, float) and scalar(sample, 'R')[0]:
            entry_format, mask = 'number', 1
            columns['duration_seconds'] = sample
        else:
            entry_format = 'value'
            value_id = write_value(connection, value=sample, **owner)
        insert(connection, 'meow_duration_samples', dict(instance=owner['instance'], month=owner['month'], kind=kind,
            bucket=bucket, ordinal=ordinal, entry_format=entry_format, hazard_present=hazard_present,
            field_mask=mask, compat_value_set_id=value_id, **columns))


def load_meow_samples(connection, instance, month, kind, bucket):
    """读取并重建喵箱收益统计样本。"""
    result = []
    fields = (('duration', 'duration_seconds', 'R'), ('hazard_level', 'observed_hazard', 'I'))
    for row in connection.execute('''SELECT * FROM meow_duration_samples
        WHERE instance=? AND month=? AND kind=? AND bucket=? ORDER BY ordinal''', (instance, month, kind, bucket)):
        if row['entry_format'] == 'value':
            result.append(read_value(connection, row['compat_value_set_id']))
        elif row['entry_format'] == 'number':
            result.append(row['duration_seconds'])
        else:
            result.append(load_row(connection, row, fields))
    return result


def save_month(connection, instance, month, data):
    """将实例月度统计快照保存到统一数据库。"""
    data = normalize(data, special=True)
    if type(data) is not dict:
        raise TypeError('月度快照必须是字典')
    register_instance(connection, instance)
    connection.execute('DELETE FROM cl1_months WHERE instance=? AND month=?', (instance, month))
    owner = {'instance': instance, 'month': month}
    columns, _, extra_scalars = project(data, MONTH_SCALARS)
    extras = {name: ('value', value) for name, value in data.items() if name not in MONTH_FIELDS}
    extras.update({name: ('value', value) for name, value in extra_scalars.items() if name in dict((f[0], f) for f in MONTH_SCALARS)})
    notification = data.get('last_ap_notification')
    notification_fields = (('ts', 'last_ap_notification_ts', 'T'), ('ap', 'last_ap_notification_value', 'I'))
    notification_columns = {field[1]: None for field in notification_fields}
    notification_mask = 0
    if 'last_ap_notification' in data:
        if type(notification) is dict:
            notification_columns, notification_mask, remaining = project(notification, notification_fields)
            if remaining:
                extras['last_ap_notification'] = ('extra', remaining)
        else:
            extras['last_ap_notification'] = ('value', notification)
    devices = data.get('siren_research_devices')
    siren_mask = presence(devices, ('cl1', 'meow')) if type(devices) is dict else 0
    insert(connection, 'cl1_months', dict(instance=instance, month=month, field_mask=presence(data, MONTH_FIELDS),
        last_ap_notification_mask=notification_mask, siren_fields_mask=siren_mask, **columns, **notification_columns))
    for name, (table, fields) in FAMILIES.items():
        if name not in data:
            continue
        records = data[name]
        if type(records) is not list:
            extras[name] = ('value', records)
            continue
        for ordinal, record in enumerate(records):
            row_id = save_row(connection, table, {'instance': instance, 'month': month, 'ordinal': ordinal}, record, fields, owner, entry=True)
            save_children(connection, table, row_id, record, owner)
    for name, kind in (('meow_round_times', 'round'), ('meow_battle_times', 'battle')):
        if name in data:
            if type(data[name]) is list:
                save_meow_samples(connection, data[name], kind, 0, owner)
            else:
                extras[name] = ('value', data[name])
    if 'meow_hazard_stats' in data:
        hazards = data['meow_hazard_stats']
        if type(hazards) is not dict:
            extras['meow_hazard_stats'] = ('value', hazards)
        else:
            remaining = {}
            for key, record in hazards.items():
                level = canonical_integer(key)
                if level not in (2, 3, 4, 5, 6) or type(record) is not dict:
                    remaining[key] = record
                    continue
                save_row(connection, 'meow_hazard_counters', {'instance': instance, 'month': month, 'hazard_level': level}, record, HAZARD_FIELDS, owner)
                for name, kind in (('round_times', 'round'), ('battle_times', 'battle')):
                    if type(record.get(name)) is list:
                        save_meow_samples(connection, record[name], kind, level, owner)
            if remaining:
                extras['meow_hazard_stats'] = ('extra', remaining)
    if 'siren_research_devices' in data:
        if type(devices) is not dict:
            extras['siren_research_devices'] = ('value', devices)
        else:
            remaining = {key: value for key, value in devices.items() if key not in ('cl1', 'meow')}
            for source in ('cl1', 'meow'):
                if source not in devices:
                    continue
                counts = {'0': devices[source]} if source == 'cl1' else devices[source]
                if type(counts) is not dict:
                    remaining[source] = counts
                    continue
                unprojected = {}
                for key, amount in counts.items():
                    level = canonical_integer(key)
                    if level is None:
                        unprojected[key] = amount
                        continue
                    valid, stored = scalar(amount, 'I')
                    value_id = None if valid else write_value(connection, value=amount, **owner)
                    insert(connection, 'siren_device_counts', dict(instance=instance, month=month, source=source,
                        hazard_level=level, device_count=stored if valid else None, compat_value_set_id=value_id))
                if unprojected:
                    remaining[source] = unprojected
            if remaining:
                extras['siren_research_devices'] = ('extra', remaining)
    for name, (mode, value) in extras.items():
        value_id = write_value(connection, value=value, **owner)
        insert(connection, 'cl1_compat_fields', dict(instance=instance, month=month, name=name, mode=mode, value_set_id=value_id))


def read_month(connection, instance, month):
    """按实例与月份读取保存的统计快照。"""
    row = connection.execute('SELECT * FROM cl1_months WHERE instance=? AND month=?', (instance, month)).fetchone()
    if row is None:
        return None
    present = {name for index, name in enumerate(MONTH_FIELDS) if row['field_mask'] & (1 << index)}
    result = {name: row[column] for name, column, _ in MONTH_SCALARS if name in present}
    if 'last_ap_notification' in present:
        result['last_ap_notification'] = {name: row[column] for index, (name, column) in enumerate(
            (('ts', 'last_ap_notification_ts'), ('ap', 'last_ap_notification_value'))) if row['last_ap_notification_mask'] & (1 << index)}
    for name, (table, fields) in FAMILIES.items():
        if name in present:
            result[name] = [load_row(connection, event, fields, load_children(connection, table, event['id']))
                for event in connection.execute(f'SELECT * FROM {table} WHERE instance=? AND month=? ORDER BY ordinal', (instance, month))]
    for name, kind in (('meow_round_times', 'round'), ('meow_battle_times', 'battle')):
        if name in present:
            result[name] = load_meow_samples(connection, instance, month, kind, 0)
    if 'meow_hazard_stats' in present:
        result['meow_hazard_stats'] = {str(hazard['hazard_level']): load_row(connection, hazard, HAZARD_FIELDS, {
            'round_times': load_meow_samples(connection, instance, month, 'round', hazard['hazard_level']),
            'battle_times': load_meow_samples(connection, instance, month, 'battle', hazard['hazard_level']),
        }) for hazard in connection.execute('SELECT * FROM meow_hazard_counters WHERE instance=? AND month=? ORDER BY hazard_level', (instance, month))}
    if 'siren_research_devices' in present:
        devices = {}
        if row['siren_fields_mask'] & 1:
            devices['cl1'] = None
        if row['siren_fields_mask'] & 2:
            devices['meow'] = {}
        for count in connection.execute('SELECT * FROM siren_device_counts WHERE instance=? AND month=?', (instance, month)):
            amount = read_value(connection, count['compat_value_set_id']) if count['compat_value_set_id'] is not None else count['device_count']
            if count['source'] == 'cl1':
                devices['cl1'] = amount
            else:
                devices.setdefault('meow', {})[str(count['hazard_level'])] = amount
        result['siren_research_devices'] = devices
    for extra in connection.execute('SELECT * FROM cl1_compat_fields WHERE instance=? AND month=? ORDER BY rowid', (instance, month)):
        value = read_value(connection, extra['value_set_id'])
        name = extra['name']
        if extra['mode'] == 'value':
            result[name] = value
        else:
            target = result.setdefault(name, {})
            if name == 'siren_research_devices' and type(value.get('meow')) is dict and type(target.get('meow')) is dict:
                target['meow'].update(value['meow'])
                value = {key: item for key, item in value.items() if key != 'meow'}
            target.update(value)
    return result


def save_ship(connection, instance, data):
    """保存指定实例的舰船经验统计快照。"""
    data = normalize(data, special=True)
    if type(data) is not dict:
        raise TypeError('舰船经验快照必须是字典')
    register_instance(connection, instance)
    connection.execute('DELETE FROM ship_exp_checks WHERE instance=?', (instance,))
    owner = {'instance': instance, 'ship': True}
    columns, _, scalar_extra = project(data, SHIP_SCALARS)
    extras = {name: ('value', value) for name, value in data.items() if name not in SHIP_FIELDS}
    extras.update({name: ('value', value) for name, value in scalar_extra.items() if name in {f[0] for f in SHIP_SCALARS}})
    insert(connection, 'ship_exp_checks', dict(instance=instance, field_mask=presence(data, SHIP_FIELDS), **columns))
    if 'ships' in data:
        if type(data['ships']) is not list:
            extras['ships'] = ('value', data['ships'])
        else:
            for ordinal, record in enumerate(data['ships']):
                save_row(connection, 'ship_exp_ships', dict(instance=instance, ordinal=ordinal), record, SHIP_ROW_FIELDS, owner, entry=True)
    for name, kind in (('battle_times', 'cl1_battle'), ('meow_battle_times', 'meow_battle'), ('round_times', 'cl1_round')):
        if name not in data:
            continue
        group = data[name]
        if type(group) is not dict:
            extras[name] = ('value', group)
            continue
        save_row(connection, 'ship_exp_duration_groups', dict(instance=instance, kind=kind), group, GROUP_FIELDS, owner)
        if type(group.get('samples')) is list:
            for ordinal, sample in enumerate(group['samples']):
                valid, stored = scalar(sample, 'R')
                valid = valid and type(sample) in (int, float)
                value_id = None if valid else write_value(connection, value=sample, **owner)
                insert(connection, 'ship_exp_duration_samples', dict(instance=instance, kind=kind, ordinal=ordinal,
                    duration_seconds=stored if valid else None, field_mask=1 if valid else 0,
                    compat_value_set_id=value_id, entry_kind='number' if valid else 'value'))
    if 'daily_stats' in data:
        if type(data['daily_stats']) is not dict:
            extras['daily_stats'] = ('value', data['daily_stats'])
        else:
            remaining = {}
            for day, record in data['daily_stats'].items():
                if type(record) is not dict:
                    remaining[day] = record
                else:
                    save_row(connection, 'ship_exp_daily', dict(instance=instance, day=day), record, SHIP_DAILY_FIELDS, owner)
            if remaining:
                extras['daily_stats'] = ('extra', remaining)
    for name, (mode, value) in extras.items():
        value_id = write_value(connection, value=value, **owner)
        insert(connection, 'ship_exp_compat_fields', dict(instance=instance, name=name, mode=mode, value_set_id=value_id))


def read_ship(connection, instance):
    """读取指定实例持久化的舰船经验统计。"""
    row = connection.execute('SELECT * FROM ship_exp_checks WHERE instance=?', (instance,)).fetchone()
    if row is None:
        return None
    present = {name for index, name in enumerate(SHIP_FIELDS) if row['field_mask'] & (1 << index)}
    result = {name: row[column] for name, column, _ in SHIP_SCALARS if name in present}
    if 'ships' in present:
        result['ships'] = [load_row(connection, item, SHIP_ROW_FIELDS) for item in connection.execute(
            'SELECT * FROM ship_exp_ships WHERE instance=? ORDER BY ordinal', (instance,))]
    for name, kind in (('battle_times', 'cl1_battle'), ('meow_battle_times', 'meow_battle'), ('round_times', 'cl1_round')):
        if name not in present:
            continue
        group = connection.execute('SELECT * FROM ship_exp_duration_groups WHERE instance=? AND kind=?', (instance, kind)).fetchone()
        samples = [read_value(connection, sample['compat_value_set_id']) if sample['entry_kind'] == 'value' else sample['duration_seconds']
            for sample in connection.execute('SELECT * FROM ship_exp_duration_samples WHERE instance=? AND kind=? ORDER BY ordinal', (instance, kind))]
        result[name] = load_row(connection, group, GROUP_FIELDS, {'samples': samples}) if group else {}
    if 'daily_stats' in present:
        result['daily_stats'] = {daily['day']: load_row(connection, daily, SHIP_DAILY_FIELDS)
            for daily in connection.execute('SELECT * FROM ship_exp_daily WHERE instance=? ORDER BY day', (instance,))}
    for extra in connection.execute('SELECT * FROM ship_exp_compat_fields WHERE instance=? ORDER BY rowid', (instance,)):
        value = read_value(connection, extra['value_set_id'])
        if extra['mode'] == 'value':
            result[extra['name']] = value
        else:
            result.setdefault(extra['name'], {}).update(value)
    return result
